"""Shadows in Postgres: tables `automation_shadows` (a run, its end time kept so any pod ends it) and
`automation_shadow_firings`."""

import logging
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg import errors

from .. import logs, services
from ..db.database import Database, DatabaseUnavailable
from ..text import has_nul
from .shadow import Settings, load
from .shadows import Firing, Kind, NewShadow, ShadowRun, Shadows, ShadowsUnavailable

log = logging.getLogger("ashley.workshop")
_RUN = "household_id, bench_id, install_seq, piece_id, version, person_id, mirrors, started_at, ends_at"


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise ShadowsUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise ShadowsUnavailable("database unreachable") from e


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _new(row: tuple[Any, ...]) -> NewShadow:
    return NewShadow(row[0], row[1], row[2], row[3], row[4], row[5], row[6], _utc(row[7]), _utc(row[8]))


class PostgresShadows(Shadows):
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    async def begin(self, run: NewShadow) -> None:
        if has_nul(run.mirrors or ""):
            raise ValueError("a shadow run's entity id may not hold a NUL")
        try:
            with _translated():
                async with self._database.connection() as conn:
                    await conn.execute(
                        f"INSERT INTO automation_shadows ({_RUN}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (run.household_id, run.bench_id, run.install_seq, run.piece_id, run.version, run.person_id,
                         run.mirrors, run.started_at, run.ends_at))
        except errors.UniqueViolation as e:
            raise ValueError("that install already has a shadow run") from e
        logs.info(log, "workshop.shadow_begun", bench=run.bench_id, seq=run.install_seq, piece=run.piece_id,
                  mirrors=run.mirrors is not None)

    async def end(self, bench_id: int, install_seq: int, now: datetime) -> bool:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "UPDATE automation_shadows SET ended_at = %s WHERE bench_id = %s AND install_seq = %s "
                    "AND ended_at IS NULL RETURNING install_seq", (now, bench_id, install_seq))
                ended = await cur.fetchone() is not None
        if ended:
            logs.info(log, "workshop.shadow_ended", bench=bench_id, seq=install_seq)
        return ended

    async def would(self, household_id: int, bench_id: int, piece_id: int, at: datetime, context: str) -> bool:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT install_seq FROM automation_shadows WHERE household_id = %s AND bench_id = %s "
                    "AND piece_id = %s AND ended_at IS NULL", (household_id, bench_id, piece_id))
                row = await cur.fetchone()
                if row is None:
                    return False
                await self._insert(conn, household_id, bench_id, row[0], "would", at, context)
        return True

    async def did(self, household_id: int, entity_id: str, at: datetime, context: str) -> int:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT bench_id, install_seq FROM automation_shadows WHERE household_id = %s AND mirrors = %s "
                    "AND ended_at IS NULL", (household_id, entity_id))
                runs = await cur.fetchall()
                for bench_id, seq in runs:
                    await self._insert(conn, household_id, bench_id, seq, "did", at, context)
        return len(runs)

    async def _insert(self, conn: psycopg.AsyncConnection[tuple[Any, ...]], household_id: int, bench_id: int, seq: int,
                      kind: Kind, at: datetime, context: str) -> None:
        if has_nul(context):
            return
        await conn.execute(
            "INSERT INTO automation_shadow_firings (household_id, bench_id, install_seq, kind, fired_at, context) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (household_id, bench_id, seq, kind, at, context))
        await conn.execute(
            "DELETE FROM automation_shadow_firings WHERE bench_id = %s AND install_seq = %s AND id NOT IN "
            "(SELECT id FROM automation_shadow_firings WHERE bench_id = %s AND install_seq = %s "
            "ORDER BY fired_at DESC, id DESC LIMIT %s)",
            (bench_id, seq, bench_id, seq, self._settings.max_events))

    async def households(self) -> tuple[int, ...]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("SELECT DISTINCT household_id FROM automation_shadows WHERE ended_at IS NULL "
                                         "ORDER BY household_id")
                return tuple(r[0] for r in await cur.fetchall())

    async def due(self, now: datetime) -> tuple[NewShadow, ...]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(f"SELECT {_RUN} FROM automation_shadows WHERE ended_at IS NULL "
                                         "AND ends_at <= %s ORDER BY ends_at, bench_id, install_seq", (now,))
                return tuple(_new(r) for r in await cur.fetchall())

    async def of_bench(self, household_id: int, bench_id: int) -> Mapping[int, ShadowRun]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    f"SELECT DISTINCT ON (piece_id) {_RUN}, ended_at FROM automation_shadows WHERE household_id = %s "
                    "AND bench_id = %s ORDER BY piece_id, install_seq DESC", (household_id, bench_id))
                runs = await cur.fetchall()
                found: dict[int, ShadowRun] = {}
                for row in runs:
                    counts = await (await conn.execute(
                        "SELECT kind, count(*) FROM automation_shadow_firings WHERE bench_id = %s AND install_seq = %s "
                        "GROUP BY kind", (bench_id, row[2]))).fetchall()
                    newest = await (await conn.execute(
                        "SELECT kind, fired_at FROM automation_shadow_firings WHERE bench_id = %s AND install_seq = %s "
                        "ORDER BY fired_at DESC, id DESC LIMIT %s", (bench_id, row[2], self._settings.shown))).fetchall()
                    by_kind = {k: int(n) for k, n in counts}
                    found[row[3]] = ShadowRun(_new(row[:9]), None if row[9] is None else _utc(row[9]),
                                              by_kind.get("would", 0), by_kind.get("did", 0),
                                              tuple(Firing(k, _utc(a)) for k, a in newest))
        return found

    async def prune(self, now: datetime) -> int:
        cutoff = now - timedelta(seconds=self._settings.keep_s)
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("DELETE FROM automation_shadow_firings WHERE fired_at < %s", (cutoff,))
                gone = cur.rowcount
                await conn.execute(
                    "DELETE FROM automation_shadows s WHERE ended_at < %s AND NOT EXISTS "
                    "(SELECT 1 FROM automation_shadow_firings f WHERE f.bench_id = s.bench_id "
                    "AND f.install_seq = s.install_seq)", (cutoff,))
        if gone:
            logs.info(log, "workshop.shadow_pruned", firings=gone)
        return gone


def register(database: Database) -> None:
    """Make `PostgresShadows` over `database`, with the tunables in `shadow.json`, the answer to `services.get(Shadows)`."""
    services.register(Shadows, PostgresShadows(database, load()))
