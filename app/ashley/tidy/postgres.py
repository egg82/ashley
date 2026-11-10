"""Tidy in Postgres: tables `bench_tidy` (per bench, the versions the last finished pass saw and when a running pass
took it) and `bench_findings`."""

from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg.types.json import Jsonb

from ..db.database import Database, DatabaseUnavailable
from .tidy import KINDS, Finding, NewFinding, Tidy, TidyUnavailable


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise TidyUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise TidyUnavailable("database unreachable") from e


class PostgresTidy(Tidy):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def checked(self, bench_id: int) -> dict[int, int]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("SELECT versions FROM bench_tidy WHERE bench_id = %s", (bench_id,))
                row = await cur.fetchone()
        return {} if row is None else {int(k): int(v) for k, v in row[0].items()}

    async def begin(self, household_id: int, bench_id: int, lock_s: int) -> bool:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO bench_tidy (bench_id, household_id, running_at) VALUES (%s, %s, now()) "
                    "ON CONFLICT (bench_id) DO UPDATE SET running_at = now() WHERE bench_tidy.running_at IS NULL "
                    "OR bench_tidy.running_at < now() - make_interval(secs => %s) RETURNING bench_id",
                    (bench_id, household_id, lock_s))
                return await cur.fetchone() is not None

    async def finish(self, household_id: int, bench_id: int, versions: dict[int, int], found: tuple[NewFinding, ...],
                     keep_s: int) -> None:
        with _translated():
            async with self._database.connection() as conn:
                await conn.execute("DELETE FROM bench_findings WHERE bench_id = %s AND (NOT dismissed OR found_at < "
                                   "now() - make_interval(secs => %s))", (bench_id, keep_s))
                for f in found:
                    await conn.execute(
                        "INSERT INTO bench_findings (bench_id, household_id, piece_id, kind, quote, by_piece_id, why) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (bench_id, piece_id, quote) DO NOTHING",
                        (bench_id, household_id, f.piece_id, f.kind, f.quote, f.by_piece_id, f.why))
                await conn.execute(
                    "UPDATE bench_tidy SET versions = %s, checked_at = now(), running_at = NULL WHERE bench_id = %s",
                    (Jsonb({str(k): v for k, v in versions.items()}), bench_id))

    async def release(self, bench_id: int) -> None:
        with _translated():
            async with self._database.connection() as conn:
                await conn.execute("UPDATE bench_tidy SET running_at = NULL WHERE bench_id = %s", (bench_id,))

    async def findings(self, bench_id: int) -> tuple[Finding, ...]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, piece_id, kind, quote, by_piece_id, why, dismissed FROM bench_findings "
                    "WHERE bench_id = %s ORDER BY id", (bench_id,))
                rows = await cur.fetchall()
        return tuple(Finding(int(r[0]), int(r[1]), next(k for k in KINDS if k == r[2]), str(r[3]),
                             None if r[4] is None else int(r[4]), str(r[5]), bool(r[6])) for r in rows)

    async def dismiss(self, bench_id: int, finding_id: int) -> bool:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("UPDATE bench_findings SET dismissed = true WHERE bench_id = %s AND id = %s "
                                         "RETURNING id", (bench_id, finding_id))
                return await cur.fetchone() is not None

    async def clear(self, bench_id: int, finding_ids: tuple[int, ...]) -> None:
        if not finding_ids:
            return
        with _translated():
            async with self._database.connection() as conn:
                await conn.execute("DELETE FROM bench_findings WHERE bench_id = %s AND id = ANY(%s)",
                                   (bench_id, list(finding_ids)))
