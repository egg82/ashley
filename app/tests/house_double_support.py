"""An in-memory `House` for tests of her house tools: states, records, configs and actions held in dicts, every change
noted in `done`, and `down` making every call raise HouseUnavailable. Nothing here is Home Assistant's own shape."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ashley.home_assistant.house import (ActionInfo, ConfigItem, ConfigKind, House, HouseRejected, HouseUnavailable,
                                         LogEntry, Performed, Reading, Record, RecordKind, Series, State, Window)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def state(entity_id: str, name: str, value: str, area: str | None = None, aliases: tuple[str, ...] = (),
          area_aliases: tuple[str, ...] = (), featured: bool = True, **attributes: object) -> State:
    return State(entity_id, name, value, entity_id.split(".", 1)[0], area, attributes, NOW, aliases, area_aliases, featured)


@dataclass
class MemoryHouse(House):
    things: list[State] = field(default_factory=list[State])
    records_of: dict[str, list[Record]] = field(default_factory=dict[str, list[Record]])
    configs_of: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict[str, dict[str, dict[str, Any]]])
    catalogue: list[ActionInfo] = field(default_factory=list[ActionInfo])
    readings: dict[str, list[Reading]] = field(default_factory=dict[str, list[Reading]])
    entries: list[LogEntry] = field(default_factory=list[LogEntry])
    reports: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    returns: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    down: bool = False
    refuse: str | None = None
    done: list[tuple[str, str, str, tuple[str, ...], Mapping[str, Any]]] = field(
        default_factory=list[tuple[str, str, str, tuple[str, ...], Mapping[str, Any]]])
    reads: int = 0

    def _up(self) -> None:
        self.reads += 1
        if self.down:
            raise HouseUnavailable("down")

    def _may(self) -> None:
        self._up()
        if self.refuse is not None:
            raise HouseRejected(self.refuse)

    def offered(self) -> bool:
        return True

    async def states(self) -> tuple[State, ...]:
        self._up()
        return tuple(self.things)

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        self._up()
        return tuple(self.records_of.get(kind, ()))

    async def history(self, window: Window) -> tuple[Series, ...]:
        self._up()
        return tuple(Series(i, tuple(self.readings.get(i, ()))) for i in window.ids)

    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        self._up()
        return tuple(e for e in self.entries if not window.ids or e.id in window.ids)

    async def actions(self) -> tuple[ActionInfo, ...]:
        self._up()
        return tuple(self.catalogue)

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        self._may()
        self.done.append(("perform", "action", action, ids, dict(data)))
        return Performed(tuple(s for s in self.things if s.id in ids), self.returns.get(action))

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        self._up()
        return tuple(ConfigItem(i, str(c.get("alias", c.get("name", i)))) for i, c in self.configs_of.get(kind, {}).items())

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        self._up()
        return self.configs_of.get(kind, {}).get(config_id)

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        self._may()
        made = config_id or f"{config.get('type', kind)}:new"
        self.configs_of.setdefault(kind, {})[made] = dict(config)
        self.done.append(("write", kind, made, (), dict(config)))
        return made

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        self._may()
        found = self.configs_of.get(kind, {}).pop(config_id, None) is not None
        self.done.append(("delete", kind, config_id, (), {}))
        return found

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        self._may()
        made = f"{kind}_new"
        self.records_of.setdefault(kind, []).append(Record(kind, made, str(fields.get("name", "")), dict(fields)))
        self.done.append(("create", kind, made, (), dict(fields)))
        return made

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        self._may()
        self.done.append(("update", kind, record_id, (), dict(fields)))

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        self._may()
        self.records_of[kind] = [r for r in self.records_of.get(kind, []) if r.id != record_id]
        self.done.append(("delete", kind, record_id, (), {}))

    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        self._up()
        return self.reports.get(integration_id)


def ago(minutes: int) -> datetime:
    """The moment `minutes` whole minutes before now, plus half a minute, so `ago_min` reads exactly `minutes`."""
    return datetime.now(UTC) - timedelta(minutes=minutes, seconds=30)
