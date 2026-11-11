"""Runs in Postgres: table `code_runs`, one row per run, its output columns empty until the run finishes."""

import logging
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from ..text import has_nul, without_nul
from .model import Artifact, BenchRun, Language, NewRun, Output, Run
from .runs import Runs, RunsUnavailable

log = logging.getLogger("ashley.runs")
_RUN = ("id, household_id, conversation_id, turn_id, call_id, language, script, stdin, files, started_at, finished_at, "
        "outcome, exit_code, stdout, stderr, cut, out_files, skipped, bench_id, bench_seq, piece_id, piece_version, artifacts")


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise RunsUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise RunsUnavailable("database unreachable") from e


def _texts(*parts: str) -> None:
    if any(has_nul(p) for p in parts):
        raise ValueError("run text may not hold a NUL")


def _utc(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(UTC)


def _run(row: tuple[Any, ...]) -> Run:
    output = None if row[11] is None else Output(row[11], row[12], row[13], row[14], row[15], dict(row[16]),
                                                tuple(row[17]))
    language: Language = row[5]
    started = _utc(row[9])
    assert started is not None
    bench = None if row[18] is None else BenchRun(row[18], row[19], row[20], row[21])
    artifacts = tuple(Artifact(a["name"], a["sha256"], a["size"], a["media_type"]) for a in row[22])
    return Run(row[0], row[1], row[2], row[3], row[4], language, row[6], row[7], dict(row[8]), started,
               _utc(row[10]), output, bench, artifacts)


async def _prune(conn: AsyncConnection[tuple[Any, ...]], bench: BenchRun, finished_id: int, turn_id: int | None) -> int:
    """Deletes the finished runs of `bench`'s piece other than its latest run, its latest that ran to its end,
    `finished_id`, the one just recorded (a later finish takes it), and the other runs of `turn_id`, the turn that asked
    for it, which `Runs.bench_runs_in_turn` counts; how many went. A run with no output yet is work in
    flight and is never deleted. Two `LIMIT 1` subqueries rather than `max()`, since `NOT IN` a NULL keeps every row."""
    cur = await conn.execute(
        "DELETE FROM code_runs WHERE bench_id = %(b)s AND piece_id = %(p)s AND outcome IS NOT NULL AND id <> %(f)s "
        "AND coalesce(turn_id = %(t)s::bigint, false) = false "
        "AND id NOT IN (SELECT id FROM code_runs WHERE bench_id = %(b)s AND piece_id = %(p)s ORDER BY id DESC LIMIT 1) "
        "AND id NOT IN (SELECT id FROM code_runs WHERE bench_id = %(b)s AND piece_id = %(p)s AND outcome = 'ran' "
        "ORDER BY id DESC LIMIT 1)", {"b": bench.bench_id, "p": bench.piece_id, "f": finished_id, "t": turn_id})
    return cur.rowcount


class PostgresRuns(Runs):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def start(self, run: NewRun) -> int:
        _texts(run.script, run.stdin, run.call_id or "", *run.files, *run.files.values())
        bench = run.bench
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO code_runs (household_id, conversation_id, turn_id, call_id, language, script, stdin, "
                    "files, bench_id, bench_seq, piece_id, piece_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (run.household_id, run.conversation_id, run.turn_id, run.call_id, run.language, run.script,
                     run.stdin, Jsonb(dict(run.files)), None if bench is None else bench.bench_id,
                     None if bench is None else bench.seq, None if bench is None else bench.piece_id,
                     None if bench is None else bench.piece_version))
                row = await cur.fetchone()
        assert row is not None
        logs.info(log, "runs.started", run=row[0], conversation=run.conversation_id, turn=run.turn_id,
                  bench=None if bench is None else bench.bench_id, piece=None if bench is None else bench.piece_id,
                  language=run.language, files=len(run.files))
        return int(row[0])

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        _texts(*output.files, *output.skipped, *(a.name for a in artifacts))
        output = replace(output, stdout=without_nul(output.stdout, "runs"), stderr=without_nul(output.stderr, "runs"),
                         files={n: without_nul(t, "runs") for n, t in output.files.items()})
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "UPDATE code_runs SET finished_at = now(), outcome = %s, exit_code = %s, stdout = %s, stderr = %s, "
                    f"cut = %s, out_files = %s, skipped = %s, artifacts = %s WHERE id = %s AND outcome IS NULL RETURNING {_RUN}",
                    (output.outcome, output.exit_code, output.stdout, output.stderr, output.cut,
                     Jsonb(dict(output.files)), Jsonb(list(output.skipped)),
                     Jsonb([asdict(a) for a in artifacts]), run_id))
                row = await cur.fetchone()
                if row is None:
                    found = await (await conn.execute("SELECT 1 FROM code_runs WHERE id = %s", (run_id,))).fetchone()
                    if found is None:
                        raise KeyError(run_id)
                    raise ValueError("this run already has its output")
                finished = _run(row)
                pruned = 0 if finished.bench is None else await _prune(conn, finished.bench, run_id, finished.turn_id)
        logs.info(log, "runs.finished", run=run_id, outcome=output.outcome, exit_code=output.exit_code,
                  files=len(output.files), artifacts=len(artifacts), cut=output.cut)
        if finished.bench is not None and pruned:
            logs.info(log, "runs.pruned", bench=finished.bench.bench_id, piece=finished.bench.piece_id, pruned=pruned)
        return finished

    async def get(self, household_id: int, run_id: int) -> Run | None:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(f"SELECT {_RUN} FROM code_runs WHERE id = %s AND household_id = %s",
                                         (run_id, household_id))
                row = await cur.fetchone()
        return None if row is None else _run(row)

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(f"SELECT {_RUN} FROM code_runs WHERE conversation_id = %s AND "
                                         "household_id = %s AND bench_id IS NULL ORDER BY id", (conversation_id, household_id))
                rows = await cur.fetchall()
        return [_run(row) for row in rows]

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        if latest == 0 or not turn_ids:
            return []
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    f"SELECT {_RUN} FROM code_runs WHERE turn_id = ANY(%s) AND household_id = %s AND bench_id IS NULL "
                    "ORDER BY id DESC LIMIT %s", (list(turn_ids), household_id, latest))
                rows = await cur.fetchall()
        return [_run(row) for row in reversed(rows)]

    async def bench_runs_in_turn(self, household_id: int, turn_id: int) -> int:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("SELECT count(*) FROM code_runs WHERE turn_id = %s AND household_id = %s "
                                         "AND bench_id IS NOT NULL", (turn_id, household_id))
                row = await cur.fetchone()
        return 0 if row is None else int(row[0])

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    f"SELECT DISTINCT ON (piece_id) {_RUN} FROM code_runs WHERE bench_id = %s AND household_id = %s "
                    "ORDER BY piece_id, id DESC", (bench_id, household_id))
                found = [_run(r) for r in await cur.fetchall()]
        return {r.bench.piece_id: r for r in found if r.bench is not None}

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT out_files FROM code_runs WHERE bench_id = %s AND household_id = %s AND piece_id = %s "
                    "AND outcome = 'ran' ORDER BY id DESC LIMIT 1", (bench_id, household_id, piece_id))
                row = await cur.fetchone()
        return {} if row is None else dict(row[0])
