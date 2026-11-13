"""Above the adapter: a recording House, a Homes giving it to a household, and the proposals store, wired."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.automations import NullAutomations
from ashley.home_assistant.client import connect
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import (ActionInfo, ConfigItem, ConfigKind, House, HouseRejected, HouseUnavailable, LogEntry,
                                         Performed, Reading, Record, RecordKind, Series, State, Window)
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from contract.conversations_support import household, person
from hag_state_support import TOKEN


class RecordingHouse(House):
    """A House that holds what it is given and notes each change asked of it, for tests above the adapter: `down`
    makes every call raise HouseUnavailable, `refuse` HouseRejected on a change, `there` is whether a config to delete
    exists."""

    def __init__(self, things: tuple[State, ...] = (), rows: Mapping[str, tuple[Record, ...]] | None = None,
                 catalogue: tuple[ActionInfo, ...] = (), there: bool = True, refuse: bool = False, down: bool = False) -> None:
        self.things, self.rows, self.catalogue = things, dict(rows or {}), catalogue
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.reads = 0
        self.there, self.refuse, self.down = there, refuse, down
        self.returns: Mapping[str, Any] | None = None

    def _read(self) -> None:
        self.reads += 1
        if self.down:
            raise HouseUnavailable("down")

    def _note(self, name: str, *args: object) -> None:
        if self.down:
            raise HouseUnavailable("down")
        if self.refuse:
            raise HouseRejected("refused")
        self.calls.append((name, args))

    def offered(self) -> bool:
        return True

    async def states(self) -> tuple[State, ...]:
        self._read()
        return self.things

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        self._read()
        return self.rows.get(kind, ())

    async def history(self, window: Window) -> tuple[Series, ...]:
        self._read()
        return tuple(Series(i, (Reading(window.start, "on"),)) for i in window.ids)

    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        self._read()
        return ()

    async def actions(self) -> tuple[ActionInfo, ...]:
        self._read()
        return self.catalogue

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        self._note("perform", action, ids, dict(data))
        return Performed((), self.returns)

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        self._read()
        return ()

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        self._read()
        return None

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        self._note("write_config", kind, config_id, dict(config))
        return config_id or "new-id"

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        self._note("delete_config", kind, config_id)
        return self.there

    async def shown_as(self, kind: ConfigKind, config_id: str) -> str | None:
        raise AssertionError("not used")

    async def set_enabled(self, thing: str, enabled: bool) -> None:
        raise AssertionError("not used")

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        self._note("create_record", kind, dict(fields))
        return f"new-{kind}"

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        self._note("update_record", kind, record_id, dict(fields))

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        self._note("delete_record", kind, record_id)

    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        self._read()
        return None


class HagHomes(Homes):
    """Each household given reaches the House it was given; every other has no Home."""

    def __init__(self) -> None:
        self.homes: dict[int, Home] = {}

    def give(self, household_id: int, house: House) -> None:
        self.homes[household_id] = Home(household_id, connect("http://127.0.0.1:9", TOKEN), NullAutomations(), house)

    async def of(self, household_id: int) -> Home | None:
        return self.homes.get(household_id)

    async def check(self, base_url: str, token: str) -> None:
        return None


@dataclass
class World:
    """A migrated database with the locator wired: Homes giving household `home` the `house`, and the proposals store."""

    url: str
    home: int
    alana: int
    sam: int
    house: RecordingHouse
    homes: HagHomes
    proposals: PostgresProposals


@asynccontextmanager
async def world(url: str, house: RecordingHouse | None = None) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    homes, store = HagHomes(), PostgresProposals(db)
    held = house or RecordingHouse()
    homes.give(home, held)
    services.register(Homes, homes)
    services.register(Proposals, store)
    try:
        yield World(url, home, person(url, home, "Alana"), person(url, home, "Sam"), held, homes, store)
    finally:
        services.unregister(Homes)
        services.unregister(Proposals)
        await db.close()
