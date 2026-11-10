"""The House port: everything she can see and change in a household's house, as neutral records. `ha_house.HaHouse`
implements it over Home Assistant's REST and WebSocket APIs; her tools (`ashley.tools.house_*`) and the proposal gate
ask only this module, so swapping Home Assistant changes the adapter alone.

Records carry ids, names and a flat `fields` mapping with the keys named per kind below; the adapter maps its own
vocabulary onto them. A record's contents are the household's data and are never logged.

Every change names an *operation key* (`perform:<action>`, `write:config:<kind>`, `delete:config:<kind>`,
`create:record:<kind>`, `update:record:<kind>`, `delete:record:<kind>`, `remove:integration`); which keys are
irreversible is data (`irreversible.json`, `irreversible.is_irreversible`), and the adapter does not decide it."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

RecordKind = Literal["device", "entity", "area", "floor", "label", "integration"]
"""device: name, area, manufacturer, model, version, integration, disabled. entity: name, domain, device, area,
integration, aliases, disabled, hidden, exposed. area: name, floor, aliases. floor: name, level, aliases. label: name.
integration: title, domain, state, disabled."""

ConfigKind = Literal["automation", "script", "helper"]
"""An automation or script is its config object; a helper is `{"type": <input_boolean|input_number|...>, ...fields}`
and its id is `<type>:<id>`."""

RECORD_KINDS: tuple[RecordKind, ...] = ("device", "entity", "area", "floor", "label", "integration")
CONFIG_KINDS: tuple[ConfigKind, ...] = ("automation", "script", "helper")


def config_kind(kind: str) -> ConfigKind | None:
    """`kind` as a ConfigKind; None when it is not one."""
    return next((k for k in CONFIG_KINDS if k == kind), None)


def record_kind(kind: str) -> RecordKind | None:
    """`kind` as a RecordKind; None when it is not one."""
    return next((k for k in RECORD_KINDS if k == kind), None)


class HouseUnavailable(Exception):
    """The house could not be reached, or answered in a way this does not read. What was asked may or may not have
    happened; the message names the step, never a body, a config or the token."""


class HouseRejected(Exception):
    """The house refused what it was given. `message` is its own reason, which names fields and nothing else."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class State:
    """One thing in the house now: its `id`, `name`, `state`, its `area` (None for none), `domain`, `attributes` and
    when its state last `changed` (None when the house does not say). `aliases` are the other names it answers to and
    `area_aliases` its area's. `featured` is whether the household lists it for her by name up front."""

    id: str
    name: str
    state: str
    domain: str
    area: str | None
    attributes: Mapping[str, Any]
    changed: datetime | None = None
    aliases: tuple[str, ...] = ()
    area_aliases: tuple[str, ...] = ()
    featured: bool = False


@dataclass(frozen=True)
class Record:
    kind: RecordKind
    id: str
    name: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class Reading:
    """One entry of a history: `state` at `at`."""

    at: datetime
    state: str


@dataclass(frozen=True)
class Series:
    id: str
    readings: tuple[Reading, ...]


@dataclass(frozen=True)
class LogEntry:
    at: datetime
    id: str | None
    name: str
    message: str


@dataclass(frozen=True)
class ActionInfo:
    """An action the house offers (`light.turn_on`): what it does, its fields (name to description), and whether it
    returns data: `none`, `optional` or `only` (an action that only returns data changes nothing)."""

    name: str
    description: str
    fields: Mapping[str, str]
    response: Literal["none", "optional", "only"]


@dataclass(frozen=True)
class Performed:
    """What an action did: the things whose state it changed, and the data it returned, if any."""

    changed: tuple[State, ...] = ()
    response: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ConfigItem:
    id: str
    name: str


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    ids: tuple[str, ...] = ()


class House(ABC):
    @abstractmethod
    def offered(self) -> bool:
        """Whether there is a house at all; her house tools are offered only then."""

    @abstractmethod
    async def states(self) -> tuple[State, ...]:
        """Everything in the house with its state, areas resolved (an entity's own, else its device's) and the
        names it answers to. Raises HouseUnavailable."""

    @abstractmethod
    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        """Every record of the kind. Raises HouseUnavailable."""

    @abstractmethod
    async def history(self, window: Window) -> tuple[Series, ...]:
        """The readings of each of `window.ids` between its start and end. Raises HouseUnavailable."""

    @abstractmethod
    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        """The entries between the window's start and end, of its ids when it names any. Raises HouseUnavailable."""

    @abstractmethod
    async def actions(self) -> tuple[ActionInfo, ...]:
        """Every action the house offers. Raises HouseUnavailable."""

    @abstractmethod
    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        """Run `action` (`domain.name`) on the things `ids` with `data`. Raises HouseRejected, HouseUnavailable."""

    @abstractmethod
    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        """Every automation, script or helper. Raises HouseUnavailable."""

    @abstractmethod
    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        """One config as the house holds it; None when there is none. Raises HouseUnavailable."""

    @abstractmethod
    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        """Create (`config_id` None for a helper; an automation or script needs an id) or replace a config; its id.
        Raises HouseRejected (nothing written), HouseUnavailable."""

    @abstractmethod
    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        """Delete a config; False when there was none. Raises HouseUnavailable."""

    @abstractmethod
    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        """Create an area, floor or label; its id. Raises HouseRejected, HouseUnavailable."""

    @abstractmethod
    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        """Change the named `fields` of a record and no others. Raises HouseRejected, HouseUnavailable."""

    @abstractmethod
    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        """Delete a record; for an integration, remove it. Raises HouseRejected, HouseUnavailable."""

    @abstractmethod
    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        """What an integration reports about itself and its devices; None when it reports nothing. Raises
        HouseUnavailable."""


class NullHouse(House):
    """No house: nothing is offered, and every call raises HouseUnavailable."""

    def offered(self) -> bool:
        return False

    async def states(self) -> tuple[State, ...]:
        raise HouseUnavailable("no house")

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        raise HouseUnavailable("no house")

    async def history(self, window: Window) -> tuple[Series, ...]:
        raise HouseUnavailable("no house")

    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        raise HouseUnavailable("no house")

    async def actions(self) -> tuple[ActionInfo, ...]:
        raise HouseUnavailable("no house")

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        raise HouseUnavailable("no house")

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        raise HouseUnavailable("no house")

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        raise HouseUnavailable("no house")

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        raise HouseUnavailable("no house")

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        raise HouseUnavailable("no house")

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        raise HouseUnavailable("no house")

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        raise HouseUnavailable("no house")

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        raise HouseUnavailable("no house")

    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        raise HouseUnavailable("no house")
