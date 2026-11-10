"""Bench jobs in Postgres, table `bench_jobs`."""

from datetime import datetime
from typing import Any, Final, Literal, LiteralString

import psycopg
from psycopg.types.json import Jsonb

from ..db.database import Database, DatabaseUnavailable
from .bench_job_model import Counts, Job, Named, NewJob, Outcome, State, Worker
from .bench_jobs import BenchJobs, JobsUnavailable
from .jobs_config import CONFIG, JobsConfig

_COLUMNS: Final = ("id, household_id, person_id, bench_id, conversation_id, turn_id, group_id, worker, title, brief, pieces, "
            "made, piece_id, state, attempts, session_id, session_seq, prompted_at, created_at, deadline_at, finished_at, reason, "
            "summary, outputs, refused")
_FINAL: Final = "('done', 'failed', 'timed_out', 'cancelled')"
_LIVE: Final = "state IN ('waiting', 'starting', 'running', 'blocked')"
_AT: Final = "id = %(id)s AND attempts = %(attempt)s"

_INSERT = """
INSERT INTO bench_jobs (household_id, person_id, bench_id, conversation_id, turn_id, group_id, worker, title, brief,
                        pieces, piece_id, state, deadline_at)
VALUES (%(household)s, %(person)s, %(bench)s, %(conversation)s, %(turn)s, %(group)s, %(worker)s, %(title)s, %(brief)s,
        %(pieces)s, %(piece)s, %(state)s,
        CASE %(state)s::text WHEN 'waiting' THEN now() + make_interval(mins => %(mins)s) END) RETURNING id"""

_CLAIM = f"""
UPDATE bench_jobs SET state = CASE worker WHEN 'claude_code' THEN 'starting' ELSE 'running' END,
    attempts = attempts + 1, claimed_at = now(),
    deadline_at = coalesce(deadline_at, now() + make_interval(mins => %(mins)s))
WHERE id = (SELECT id FROM bench_jobs WHERE state = 'due' AND worker = %(worker)s ORDER BY created_at, id LIMIT 1
            FOR UPDATE SKIP LOCKED)
RETURNING {_COLUMNS}"""

_LAPSED = """
WITH lapsed AS (
    SELECT id, attempts FROM bench_jobs
    WHERE ((worker = 'agent' AND state = 'running') OR state = 'starting')
      AND claimed_at < coalesce(%(now)s::timestamptz, now()) - make_interval(secs => %(claim)s) FOR UPDATE),
retaken AS (
    UPDATE bench_jobs j SET state = 'due', claimed_at = NULL FROM lapsed
    WHERE j.id = lapsed.id AND lapsed.attempts < %(max)s RETURNING 1),
failed AS (
    UPDATE bench_jobs j SET state = 'failed', reason = 'attempts', finished_at = now() FROM lapsed
    WHERE j.id = lapsed.id AND lapsed.attempts >= %(max)s RETURNING 1)
SELECT (SELECT count(*) FROM retaken), (SELECT count(*) FROM failed)"""

_TIMED_OUT = f"""
UPDATE bench_jobs SET state = 'timed_out', reason = 'group_timeout', finished_at = now()
WHERE state NOT IN {_FINAL}
  AND group_id IN (SELECT group_id FROM bench_jobs GROUP BY group_id
                   HAVING min(created_at) < coalesce(%(now)s::timestamptz, now()) - make_interval(mins => %(mins)s))"""

_FINISH = f"""
UPDATE bench_jobs SET state = %(state)s, reason = %(reason)s, summary = %(summary)s, outputs = %(outputs)s,
    refused = %(refused)s, finished_at = now()
WHERE {_AT} AND {_LIVE} RETURNING 1"""

_STATE = """
UPDATE bench_jobs SET state = %(to)s WHERE {at} AND state = ANY(%(from)s) RETURNING 1"""


class PostgresBenchJobs(BenchJobs):
    def __init__(self, database: Database, config: JobsConfig = CONFIG) -> None:
        self._database = database
        self._config = config

    async def start_group(self, jobs: tuple[NewJob, ...]) -> tuple[int, tuple[int, ...]]:
        try:
            async with self._database.connection() as conn:
                group = int((await (await conn.execute("SELECT nextval('bench_job_groups')")).fetchone() or [0])[0])
                ids: list[int] = []
                for j in jobs:
                    cur = await conn.execute(_INSERT, {
                        "household": j.household, "person": j.person, "bench": j.bench, "conversation": j.conversation,
                        "turn": j.turn, "group": group, "worker": j.worker, "title": j.title, "brief": j.brief,
                        "pieces": Jsonb([_named(n) for n in j.pieces]), "piece": j.piece_id,
                        "state": "waiting" if j.waiting else "due", "mins": self._config.deadline_min[j.worker]})
                    ids.append(int((await cur.fetchone() or [0])[0]))
                return group, tuple(ids)
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise JobsUnavailable("database unavailable") from e

    async def start(self, job: NewJob) -> int:
        return (await self.start_group((job,)))[1][0]

    async def running(self, household_id: int, person_id: int, worker: Worker) -> int:
        rows = await self._run("SELECT count(*) FROM bench_jobs WHERE household_id = %s AND person_id = %s "
                               f"AND worker = %s AND state NOT IN {_FINAL}", (household_id, person_id, worker))
        return int(rows[0][0])

    async def claim(self, worker: Worker, claim_s: float) -> Job | None:
        rows = await self._run(_CLAIM, {"worker": worker, "mins": self._config.deadline_min[worker]})
        return _job(rows[0]) if rows else None

    async def active(self, worker: Worker) -> tuple[Job, ...]:
        rows = await self._run(f"SELECT {_COLUMNS} FROM bench_jobs WHERE worker = %s AND {_LIVE} ORDER BY created_at, id",
                               (worker,))
        return tuple(_job(r) for r in rows)

    async def unfinished(self) -> tuple[Job, ...]:
        rows = await self._run(f"SELECT {_COLUMNS} FROM bench_jobs WHERE state NOT IN {_FINAL} ORDER BY created_at, id", ())
        return tuple(_job(r) for r in rows)

    async def heartbeat(self, job_id: int, attempt: int) -> bool:
        return await self._changed(f"UPDATE bench_jobs SET claimed_at = now() WHERE {_AT} AND {_LIVE} RETURNING 1",
                                   {"id": job_id, "attempt": attempt})

    async def made(self, job_id: int, attempt: int, piece_id: int) -> bool:
        return await self._changed(
            "UPDATE bench_jobs SET made = CASE WHEN %(piece)s = ANY(made) THEN made ELSE array_append(made, %(piece)s) END "
            f"WHERE {_AT} AND {_LIVE} RETURNING 1", {"id": job_id, "attempt": attempt, "piece": piece_id})

    async def started(self, job_id: int, attempt: int, session_id: str, seq: int | None = None) -> bool:
        return await self._changed(f"UPDATE bench_jobs SET session_id = %(session)s, session_seq = %(seq)s "
                                   f"WHERE {_AT} AND state = 'starting' RETURNING 1",
                                   {"id": job_id, "attempt": attempt, "session": session_id, "seq": seq})

    async def prompted(self, job_id: int, attempt: int) -> bool:
        return await self._changed(f"UPDATE bench_jobs SET prompted_at = now() WHERE {_AT} AND state = 'starting' "
                                   "AND session_id IS NOT NULL RETURNING 1", {"id": job_id, "attempt": attempt})

    async def state(self, job_id: int, attempt: int, state: Literal["running", "blocked", "waiting"]) -> bool:
        before = {"running": ["starting", "blocked"], "blocked": ["starting", "running"], "waiting": ["starting"]}[state]
        return await self._changed(_STATE.format(at=_AT), {"id": job_id, "attempt": attempt, "to": state,
                                                           "from": before})

    async def resume(self, job_id: int, attempt: int) -> bool:
        return await self._changed("UPDATE bench_jobs SET state = 'due', claimed_at = NULL "
                                   f"WHERE {_AT} AND state = 'waiting' RETURNING 1", {"id": job_id, "attempt": attempt})

    async def finish(self, job_id: int, attempt: int, outcome: Outcome) -> bool:
        return await self._changed(_FINISH, {"id": job_id, "attempt": attempt, "state": outcome.state,
                                             "reason": outcome.reason, "summary": outcome.summary,
                                             "outputs": list(outcome.outputs), "refused": outcome.refused})

    async def cancel(self, household_id: int, person_id: int, job_id: int) -> bool:
        return await self._changed(
            f"UPDATE bench_jobs SET state = 'cancelled', finished_at = now() WHERE id = %s AND household_id = %s "
            f"AND person_id = %s AND state NOT IN {_FINAL} RETURNING 1", (job_id, household_id, person_id))

    async def due_closes(self) -> tuple[Job, ...]:
        rows = await self._run(f"SELECT {_COLUMNS} FROM bench_jobs WHERE state IN {_FINAL} AND worker = 'claude_code' "
                               "AND session_id IS NOT NULL AND closed_at IS NULL ORDER BY id", ())
        return tuple(_job(r) for r in rows)

    async def closed(self, job_id: int) -> None:
        await self._run("UPDATE bench_jobs SET closed_at = now() WHERE id = %s AND closed_at IS NULL", (job_id,))

    async def sweep(self, claim_s: float, now: datetime | None = None) -> Counts:
        try:
            async with self._database.connection() as conn:
                row = await (await conn.execute(_LAPSED, {"now": now, "claim": claim_s,
                                                          "max": self._config.max_attempts})).fetchone() or (0, 0)
                cur = await conn.execute(_TIMED_OUT, {"now": now, "mins": self._config.group_timeout_min})
                return Counts(int(row[0]), int(row[1]), cur.rowcount)
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise JobsUnavailable("database unavailable") from e

    async def get(self, household_id: int, person_id: int, job_id: int) -> Job | None:
        rows = await self._run(f"SELECT {_COLUMNS} FROM bench_jobs WHERE id = %s AND household_id = %s AND person_id = %s",
                               (job_id, household_id, person_id))
        return _job(rows[0]) if rows else None

    async def group(self, household_id: int, person_id: int, group_id: int) -> tuple[Job, ...]:
        rows = await self._run(f"SELECT {_COLUMNS} FROM bench_jobs WHERE group_id = %s AND household_id = %s "
                               "AND person_id = %s ORDER BY id", (group_id, household_id, person_id))
        return tuple(_job(r) for r in rows)

    async def group_settled(self, group_id: int) -> tuple[Job, ...] | None:
        rows = await self._run(f"SELECT {_COLUMNS} FROM bench_jobs WHERE group_id = %s ORDER BY id", (group_id,))
        jobs = tuple(_job(r) for r in rows)
        return jobs if jobs and all(j.final for j in jobs) else None

    async def _changed(self, query: LiteralString, params: tuple[Any, ...] | dict[str, Any]) -> bool:
        return bool(await self._run(query, params))

    async def _run(self, query: LiteralString, params: tuple[Any, ...] | dict[str, Any]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall() if cur.description is not None else []
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise JobsUnavailable("database unavailable") from e


def _named(n: Named) -> dict[str, Any]:
    return {"id": n.piece_id, "run_files": n.run_files}


def _job(r: tuple[Any, ...]) -> Job:
    worker: Worker = "claude_code" if r[7] == "claude_code" else "agent"
    state: State = r[13]
    pieces = tuple(Named(int(p["id"]), bool(p["run_files"])) for p in r[10])
    return Job(int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]), int(r[6]), worker, str(r[8]),
               str(r[9]), pieces, tuple(int(m) for m in r[11]), int(r[12]), state, int(r[14]),
               None if r[15] is None else str(r[15]), None if r[16] is None else int(r[16]), r[17], r[18], r[19], r[20],
               None if r[21] is None else str(r[21]), None if r[22] is None else str(r[22]),
               tuple(int(o) for o in r[23]), int(r[24]))
