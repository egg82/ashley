"""SettingsReader in Postgres, tables `connection_settings` and `connection_settings_log`."""

import logging

from .. import logs, services
from ..db.database import Database
from .connections import ConnectionsUnavailable
from .kinds import ConnectionKinds
from .model import Port
from .rows import translated
from .settings import SettingValues
from .settings_read import Change, SettingsReader, StoredSettings

log = logging.getLogger("ashley.connections")

OF_PORT = ("SELECT s.values FROM connection_settings s JOIN connections c ON c.id = s.connection_id "
           "WHERE c.household_id = %(household)s AND c.person_id IS NULL AND c.kind = ANY(%(kinds)s::text[]) "
           "ORDER BY array_position(%(kinds)s::text[], c.kind), c.label, c.id LIMIT 1")
STORED = ("SELECT version, values, updated_at, updated_by FROM connection_settings "
          "WHERE connection_id = %(id)s AND household_id = %(household)s")
HISTORY = ("SELECT id, key, changed_by, changed_at FROM connection_settings_log "
           "WHERE connection_id = %(id)s AND household_id = %(household)s AND (%(before)s::bigint IS NULL OR id < %(before)s) "
           "ORDER BY id DESC LIMIT %(limit)s")


class PostgresSettingsReader(SettingsReader):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def of(self, household_id: int, port: Port) -> SettingValues:
        kinds = [k.name for k in services.get(ConnectionKinds).of_port(port)]
        try:
            with translated():
                async with self._database.connection() as conn:
                    row = await (await conn.execute(OF_PORT, {"household": household_id, "kinds": kinds})).fetchone()
        except ConnectionsUnavailable:
            logs.warning(log, "settings.unreadable", household=household_id, port=port)
            return {}
        return {} if row is None else row[0]

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        with translated():
            async with self._database.connection() as conn:
                row = await (await conn.execute(STORED, {"id": connection_id, "household": household_id})).fetchone()
        return StoredSettings(0, {}, None, None) if row is None else StoredSettings(row[0], row[1], row[2], row[3])

    async def history(self, connection_id: int, household_id: int, limit: int,
                      before: int | None = None) -> tuple[Change, ...]:
        args = {"id": connection_id, "household": household_id, "limit": limit, "before": before}
        with translated():
            async with self._database.connection() as conn:
                rows = await (await conn.execute(HISTORY, args)).fetchall()
        return tuple(Change(r[0], r[1], r[2], r[3]) for r in rows)
