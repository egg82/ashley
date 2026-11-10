"""Installs in Postgres: table `bench_installs`, one row per Install or Undo of one, its ending empty until it ends."""

import logging
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from ..text import has_nul
from .installs import Before, Ending, InstallRecord, Installs, InstallsUnavailable, NewInstall

log = logging.getLogger("ashley.workshop")
_ROW = ("household_id, bench_id, seq, piece_id, action, automation_id, enabled, turn_off, before, touched, started_at, "
        "ending, note, finished_at")


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise InstallsUnavailable("no database connection") from e
    except errors.UniqueViolation as e:
        raise ValueError("that command already has an install record") from e
    except psycopg.OperationalError as e:
        raise InstallsUnavailable("database unreachable") from e


def _before(raw: Any) -> Before | None:
    if raw is None:
        return None
    return Before(raw["config"], raw["enabled"], raw["turn_off_was_on"])


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _record(row: tuple[Any, ...]) -> InstallRecord:
    started = NewInstall(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], _before(row[8]), row[9])
    return InstallRecord(started, _utc(row[10]), row[11], row[12], None if row[13] is None else _utc(row[13]))


class PostgresInstalls(Installs):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def start(self, install: NewInstall) -> None:
        before = install.before
        stored = None if before is None else {"config": None if before.config is None else dict(before.config),
                                              "enabled": before.enabled, "turn_off_was_on": before.turn_off_was_on}
        if has_nul(install.automation_id + (install.turn_off or "")):
            raise ValueError("an install's ids may not hold a NUL")
        with _translated():
            async with self._database.connection() as conn:
                await conn.execute(
                    "INSERT INTO bench_installs (household_id, bench_id, seq, piece_id, action, automation_id, enabled, "
                    "turn_off, before, touched) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (install.household_id, install.bench_id, install.seq, install.piece_id, install.action,
                     install.automation_id, install.enabled, install.turn_off, None if stored is None else Jsonb(stored),
                     install.touched))
        logs.info(log, "workshop.install_started", bench=install.bench_id, seq=install.seq, piece=install.piece_id,
                  action=install.action, automation=install.automation_id, touched=install.touched)

    async def finish(self, bench_id: int, seq: int, ending: Ending, note: str | None) -> None:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "UPDATE bench_installs SET ending = %s, note = %s, finished_at = now() "
                    "WHERE bench_id = %s AND seq = %s AND ending IS NULL RETURNING seq", (ending, note, bench_id, seq))
                if await cur.fetchone() is None:
                    found = await (await conn.execute("SELECT 1 FROM bench_installs WHERE bench_id = %s AND seq = %s",
                                                      (bench_id, seq))).fetchone()
                    if found is None:
                        raise KeyError(seq)
                    raise ValueError("this install has already ended")
        logs.info(log, "workshop.install_finished", bench=bench_id, seq=seq, ending=ending)

    async def of(self, household_id: int, bench_id: int, seq: int) -> InstallRecord | None:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(f"SELECT {_ROW} FROM bench_installs WHERE household_id = %s AND bench_id = %s "
                                         "AND seq = %s", (household_id, bench_id, seq))
                row = await cur.fetchone()
        return None if row is None else _record(row)

    async def wrote_before(self, household_id: int, bench_id: int, piece_id: int) -> bool:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM bench_installs WHERE household_id = %s AND bench_id = %s "
                    "AND piece_id = %s AND touched AND ending IS DISTINCT FROM 'refused')",
                    (household_id, bench_id, piece_id))
                row = await cur.fetchone()
        return row is not None and bool(row[0])

    async def latest_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, InstallRecord]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    f"SELECT DISTINCT ON (piece_id) {_ROW} FROM bench_installs WHERE household_id = %s AND bench_id = %s "
                    "ORDER BY piece_id, seq DESC", (household_id, bench_id))
                found = [_record(r) for r in await cur.fetchall()]
        return {r.started.piece_id: r for r in found}
