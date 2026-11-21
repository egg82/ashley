"""Sealing every stored value again under the current connections key: the singleton that finishes a rotation of
`CONNECTIONS_KEY` (`decisions.md`, "The connections key rotates in place"). It runs under the lease `reseal`, so on one
site at a time, and only when `CONNECTIONS_KEY_OPENS` names a second key.

A pass walks each column of `reseal_columns.SEALED` in key order, `batch` rows at a time, each batch its own
transaction. Only rows not sealed under the current version are read, so a pass cut short by a dying pod loses nothing
and the next holder's pass carries on where the rows say. A row is written only if it still holds the value that was
read; one a pod wrote meanwhile (under the current key) is `raced` and left. A value that opens under neither key is
left as it is, counted and logged by row id; the next pass counts it again.

Logs `reseal.start`, `reseal.batch` (column, rows, `resealed`, `raced`, `unsealable`), `reseal.unsealable` (column, row
id; no row id for a column keyed by a hash), `reseal.finish` (counts, `duration_ms`) and `reseal.unavailable` when the
database fails a pass. Never a value, a key or a hash."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import AsyncConnection

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from .reseal_columns import SEALED, SealedColumn
from .sealing import Sealer, Unsealable

log = logging.getLogger("ashley.connections")

NAME = "reseal"
BATCH = 50
INTERVAL_S = 3600.0


@dataclass(frozen=True)
class Tally:
    resealed: int = 0
    raced: int = 0
    unsealable: int = 0

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(self.resealed + other.resealed, self.raced + other.raced, self.unsealable + other.unsealable)


def _select(c: SealedColumn) -> str:
    extra = "".join(f", {e}" for e in c.extra)
    return (f"SELECT {c.key}, {c.column}{extra} FROM {c.table} WHERE {c.column} IS NOT NULL "
            f"AND substring({c.column} from 1 for 1) <> %(version)s::bytea "
            f"AND (%(after)s::{c.key_type} IS NULL OR {c.key} > %(after)s::{c.key_type}) ORDER BY {c.key} LIMIT %(n)s")


def _update(c: SealedColumn) -> str:
    return f"UPDATE {c.table} SET {c.column} = %(new)s WHERE {c.key} = %(key)s AND {c.column} = %(old)s"


async def _batch(conn: AsyncConnection[tuple[Any, ...]], sealer: Sealer, c: SealedColumn,
                 rows: list[tuple[Any, ...]]) -> Tally:
    resealed = raced = unsealable = 0
    for row in rows:
        old = bytes(row[1])
        try:
            new = sealer.seal(sealer.open(old, c.bound(row[2:])), c.bound(row[2:]))
        except Unsealable:
            unsealable += 1
            logs.warning(log, "reseal.unsealable", column=c.name, row=row[0] if c.shown else "-")
            continue
        cur = await conn.execute(_update(c).encode(), {"new": new, "key": row[0], "old": old})
        if cur.rowcount == 1:
            resealed += 1
        else:
            raced += 1
    return Tally(resealed, raced, unsealable)


async def reseal_column(database: Database, sealer: Sealer, c: SealedColumn, batch: int = BATCH) -> Tally:
    """Every row of `c` not sealed under the current key, sealed under it. Raises what the database raises."""
    total, after = Tally(), None
    while True:
        async with database.connection() as conn:
            args = {"version": bytes([sealer.current]), "after": after, "n": batch}
            rows = await (await conn.execute(_select(c).encode(), args)).fetchall()
            if not rows:
                return total
            done = await _batch(conn, sealer, c, rows)
        logs.info(log, "reseal.batch", column=c.name, rows=len(rows), resealed=done.resealed, raced=done.raced,
                  unsealable=done.unsealable)
        total, after = total + done, rows[-1][0]


async def reseal_all(database: Database, sealer: Sealer, batch: int = BATCH) -> Tally:
    """One pass over every column in `SEALED`."""
    logs.info(log, "reseal.start", version=sealer.current, columns=len(SEALED))
    started, total = time.monotonic(), Tally()
    for c in SEALED:
        total += await reseal_column(database, sealer, c, batch)
    logs.info(log, "reseal.finish", resealed=total.resealed, raced=total.raced, unsealable=total.unsealable,
              duration_ms=round((time.monotonic() - started) * 1000))
    return total


async def run(database: Database, sealer: Sealer, batch: int = BATCH, interval_s: float = INTERVAL_S,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """A pass, then another every `interval_s`, until cancelled. A pass the database fails is logged and tried again
    at the next interval."""
    while True:
        try:
            await reseal_all(database, sealer, batch)
        except (DatabaseUnavailable, psycopg.Error):
            logs.error(log, "reseal.unavailable", exc=True)
        await sleep(interval_s)
