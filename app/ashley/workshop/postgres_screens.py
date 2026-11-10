"""The SQL of a device's screen bench (a bench of `benches.device_id`, owner null), one statement per function, each on a
connection the caller holds in its transaction. The pieces and the log are the bench tables' own (`postgres_rows`)."""

from typing import Any

from psycopg import AsyncConnection

from . import screen_seed
from .screen_controls import ACTIONS, Control

Conn = AsyncConnection[tuple[Any, ...]]


async def device_is_live(conn: Conn, household_id: int, device_id: int, lock: bool = False) -> bool:
    """Whether the household has an unrevoked device `device_id`; its row is locked for this transaction when `lock`."""
    cur = await conn.execute(
        "SELECT 1 FROM devices WHERE id = %s AND household_id = %s AND revoked_at IS NULL"
        + (" FOR UPDATE" if lock else ""), (device_id, household_id))
    return await cur.fetchone() is not None


async def person_is_of(conn: Conn, household_id: int, person_id: int) -> bool:
    cur = await conn.execute("SELECT 1 FROM people WHERE id = %s AND household_id = %s", (person_id, household_id))
    return await cur.fetchone() is not None


async def bench(conn: Conn, household_id: int, device_id: int, lock: bool = False) -> tuple[int, int, str] | None:
    """The device's screen bench as its id, next seq and title; locked for this transaction when `lock`."""
    cur = await conn.execute(
        "SELECT id, next_seq, title FROM benches WHERE device_id = %s AND household_id = %s"
        + (" FOR UPDATE" if lock else ""), (device_id, household_id))
    row = await cur.fetchone()
    return None if row is None else (int(row[0]), int(row[1]), str(row[2]))


async def insert_bench(conn: Conn, household_id: int, device_id: int) -> int | None:
    """A new screen bench of the device, its id; None when the device already has one."""
    cur = await conn.execute(
        "INSERT INTO benches (household_id, device_id, title) VALUES (%s, %s, %s) "
        "ON CONFLICT (device_id) WHERE device_id IS NOT NULL DO NOTHING RETURNING id",
        (household_id, device_id, screen_seed.TITLE))
    row = await cur.fetchone()
    return None if row is None else int(row[0])


async def device_controls(conn: Conn, household_id: int, device_id: int) -> tuple[Control, ...]:
    """The device's `device_controls` rows in order: its buttons until its screen bench exists."""
    cur = await conn.execute(
        "SELECT name, label, action, entity_id FROM device_controls WHERE device_id = %s AND household_id = %s "
        "ORDER BY position", (device_id, household_id))
    return tuple(Control(name, label, ACTIONS[action], entity) for name, label, action, entity in await cur.fetchall())


async def delete_device_controls(conn: Conn, device_id: int) -> None:
    await conn.execute("DELETE FROM device_controls WHERE device_id = %s", (device_id,))
