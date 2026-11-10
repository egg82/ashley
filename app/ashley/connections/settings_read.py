"""The SettingsReader service (`ashley.services`): what a person set on a connection (`ashley.connections.settings`).
Reading is open to every system that behaves by a setting; writing is `settings_write`, which her tools, channels and
inference never import (`tests/test_settings_boundary.py`)."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..services import Service
from .connections import ConnectionsUnavailable
from .model import Port
from .settings import SettingValue, SettingValues


@dataclass(frozen=True)
class StoredSettings:
    """A connection's settings as last written: `version` counts the writes (0 for a connection never set), `values`
    are by key, `updated_at` and `updated_by` (a person id, None once they are gone) say who wrote them last."""

    version: int
    values: dict[str, SettingValue]
    updated_at: datetime | None
    updated_by: int | None


@dataclass(frozen=True)
class Change:
    """One key a write changed: the log row's `id` (what `history` pages by), who and when."""

    id: int
    key: str
    changed_by: int | None
    changed_at: datetime


class SettingsReader(Service):
    @classmethod
    def null(cls) -> "SettingsReader":
        return NullSettingsReader()

    @abstractmethod
    async def of(self, household_id: int, port: Port) -> SettingValues:
        """The settings of the household's own connection that serves `port`, none when it has none. Never raises:
        settings that cannot be read are none, which is the least trust (everything outside, nothing listed), logged
        `settings.unreadable`."""

    @abstractmethod
    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        """That connection's settings with their version; version 0 and no values when none were written. Raises
        ConnectionsUnavailable."""

    @abstractmethod
    async def history(self, connection_id: int, household_id: int, limit: int,
                      before: int | None = None) -> tuple[Change, ...]:
        """The keys changed on that connection, newest first, `limit` of them, those of a log row before `before`
        when given. Raises ConnectionsUnavailable."""


class NullSettingsReader(SettingsReader):
    """Nothing is set."""

    async def of(self, household_id: int, port: Port) -> SettingValues:
        return {}

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        raise ConnectionsUnavailable("settings are not wired")

    async def history(self, connection_id: int, household_id: int, limit: int,
                      before: int | None = None) -> tuple[Change, ...]:
        raise ConnectionsUnavailable("settings are not wired")
