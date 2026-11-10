"""Device controls in Postgres, table `device_controls`: one row per control, ordered by `position`, gone with the
device."""

import logging

import psycopg

from ... import logs
from ...db.database import Database, DatabaseUnavailable
from .controls import ACTIONS, Control
from .device_controls import ControlsUnavailable, DeviceControls

log = logging.getLogger("ashley.channels.kiosk")


class PostgresDeviceControls(DeviceControls):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def of_device(self, device_id: int, household_id: int) -> tuple[Control, ...]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT name, label, action, entity_id FROM device_controls "
                    "WHERE device_id = %s AND household_id = %s ORDER BY position", (device_id, household_id))
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise ControlsUnavailable("database unreachable") from e
        return tuple(Control(name, label, ACTIONS[action], entity) for name, label, action, entity in rows)

    async def replace(self, device_id: int, household_id: int, controls: tuple[Control, ...]) -> bool:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT 1 FROM devices WHERE id = %s AND household_id = %s AND revoked_at IS NULL FOR UPDATE",
                    (device_id, household_id))
                if await cur.fetchone() is None:
                    return False
                await conn.execute("DELETE FROM device_controls WHERE device_id = %s", (device_id,))
                async with conn.cursor() as write:
                    await write.executemany(
                        "INSERT INTO device_controls (device_id, household_id, name, position, label, action, entity_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [(device_id, household_id, c.id, n, c.label, c.action, c.entity_id)
                         for n, c in enumerate(controls)])
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise ControlsUnavailable("database unreachable") from e
        logs.info(log, "device_controls.replaced", device=device_id, household=household_id, count=len(controls))
        return True
