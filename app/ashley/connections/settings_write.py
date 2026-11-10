"""The SettingsWriter service (`ashley.services`): a person's write of a connection's settings. Only the member route
imports this module (`ashley.api.connection_settings`) and the wiring that registers it; a boundary test holds that
set to exactly those, so nothing she does on her own, by tool, channel or model, can widen what she trusts."""

from abc import abstractmethod

from ..services import Service
from .connections import ConnectionsUnavailable
from .kinds import ConnectionKind
from .settings import SettingValues
from .settings_read import StoredSettings

RETAIN_DAYS = 400
"""How long the change log is kept; each write deletes what is older."""


class VersionConflict(Exception):
    """The settings changed since the version the writer read."""


class SettingsWriter(Service):
    @classmethod
    def null(cls) -> "SettingsWriter":
        return NullSettingsWriter()

    @abstractmethod
    async def put(self, kind: ConnectionKind, connection_id: int, household_id: int, person_id: int, version: int,
                  values: SettingValues) -> StoredSettings | None:
        """Replace the whole of a household's connection's settings with `values`, which must be what `version` was
        when read (0 for a connection never set): compare-and-set, in one transaction with a log row per changed
        key, and the log pruned past `RETAIN_DAYS`. None when the household has no such connection. Logs
        `connections.settings.changed` with key names, never values. Raises SettingsInvalid, VersionConflict,
        ConnectionsUnavailable."""


class NullSettingsWriter(SettingsWriter):
    async def put(self, kind: ConnectionKind, connection_id: int, household_id: int, person_id: int, version: int,
                  values: SettingValues) -> StoredSettings | None:
        raise ConnectionsUnavailable("settings are not wired")
