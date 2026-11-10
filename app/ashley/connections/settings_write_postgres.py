"""SettingsWriter in Postgres. One transaction per write: the connection row is locked, the version compared, the
settings replaced whole, a log row written per changed key and the log pruned."""

import logging

from psycopg.types.json import Jsonb

from .. import logs
from ..db.database import Database
from .kinds import ConnectionKind
from .rows import translated
from .settings import SettingValue, SettingValues, validate
from .settings_read import StoredSettings
from .settings_write import RETAIN_DAYS, SettingsWriter, VersionConflict

log = logging.getLogger("ashley.connections")

LOCK = "SELECT 1 FROM connections WHERE id = %(id)s AND household_id = %(household)s AND person_id IS NULL FOR UPDATE"
CURRENT = "SELECT version, values FROM connection_settings WHERE connection_id = %(id)s FOR UPDATE"
INSERT = ("INSERT INTO connection_settings (connection_id, household_id, values, version, updated_at, updated_by) "
          "VALUES (%(id)s, %(household)s, %(values)s, 1, now(), %(person)s) RETURNING version, values, updated_at, updated_by")
UPDATE = ("UPDATE connection_settings SET values = %(values)s, version = version + 1, updated_at = now(), "
          "updated_by = %(person)s WHERE connection_id = %(id)s RETURNING version, values, updated_at, updated_by")
LOGGED = ("INSERT INTO connection_settings_log (connection_id, household_id, changed_by, key, before, after) "
          "VALUES (%(id)s, %(household)s, %(person)s, %(key)s, %(before)s, %(after)s)")
PRUNE = "DELETE FROM connection_settings_log WHERE changed_at < now() - make_interval(days => %(days)s)"


def changed_keys(before: dict[str, SettingValue], after: dict[str, SettingValue]) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def _json(value: SettingValue | None) -> Jsonb | None:
    return None if value is None else Jsonb(value)


class PostgresSettingsWriter(SettingsWriter):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def put(self, kind: ConnectionKind, connection_id: int, household_id: int, person_id: int, version: int,
                  values: SettingValues) -> StoredSettings | None:
        checked = validate(kind.settings, values)
        args = {"id": connection_id, "household": household_id, "person": person_id}
        with translated():
            async with self._database.connection() as conn:
                if await (await conn.execute(LOCK, args)).fetchone() is None:
                    return None
                current = await (await conn.execute(CURRENT, args)).fetchone()
                held = 0 if current is None else current[0]
                before: dict[str, SettingValue] = {} if current is None else current[1]
                if held != version:
                    raise VersionConflict
                row = await (await conn.execute(INSERT if current is None else UPDATE,
                                                {**args, "values": Jsonb(checked)})).fetchone()
                keys = changed_keys(before, checked)
                for key in keys:
                    await conn.execute(LOGGED, {**args, "key": key, "before": _json(before.get(key)),
                                                "after": _json(checked.get(key))})
                await conn.execute(PRUNE, {"days": RETAIN_DAYS})
        assert row is not None
        logs.info(log, "connections.settings.changed", household=household_id, person=person_id, kind=kind.name,
                  connection=connection_id, keys=len(keys), changed=",".join(keys), version=row[0])
        return StoredSettings(row[0], row[1], row[2], row[3])
