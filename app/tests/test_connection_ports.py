"""Opening a connection by port: the first visible connection of a kind of the port, in kind registration order, then
label, then id."""

import asyncio
import dataclasses
from typing import get_args
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.connections import ports
from ashley.connections.connections import NullConnections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import PORTS, Connection, Kind, Opened, Port
from ashley.connections.settings_read import Change, SettingsReader, StoredSettings
from ashley.home_assistant.kind import HOME_ASSISTANT

NOW = datetime.now(UTC)


class Holding(NullConnections):
    """Connections as (kind, label) pairs, numbered from 1 in the order given."""

    def __init__(self, held: list[tuple[Kind, str]]) -> None:
        self.held = [Connection(i, 1, kind, "https://x.test", None, NOW, NOW, None, label)
                     for i, (kind, label) in enumerate(held, 1)]
        self.asked: list[tuple[int, int | None]] = []

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        return tuple(sorted(self.held, key=lambda c: (c.kind, c.label, c.id)))

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        self.asked.append((connection_id, person_id))
        found = next((c for c in self.held if c.id == connection_id), None)
        return None if found is None else Opened(found, "s")


@pytest.fixture
def second_house() -> None:
    other = dataclasses.replace(HOME_ASSISTANT, name="openhab")
    services.register(ConnectionKinds, ConnectionKinds((HOME_ASSISTANT, other)))


@pytest.mark.usefixtures("second_house")
def test_the_port_opens_whichever_kind_the_household_holds() -> None:
    opened = asyncio.run(ports.opened(Holding([("openhab", "")]), "house", 1))
    assert opened is not None and opened.connection.kind == "openhab"


@pytest.mark.usefixtures("second_house")
def test_the_first_kind_in_registration_order_wins() -> None:
    opened = asyncio.run(ports.opened(Holding([("openhab", ""), ("home_assistant", "")]), "house", 1))
    assert opened is not None and opened.connection.kind == "home_assistant"


@pytest.fixture
def two_mailers() -> None:
    first = dataclasses.replace(HOME_ASSISTANT, ports=frozenset({"mail"}))
    other = dataclasses.replace(first, name="openhab")
    services.register(ConnectionKinds, ConnectionKinds((first, other)))


@pytest.mark.usefixtures("two_mailers")
def test_a_combine_port_lists_every_connection_in_order_and_opened_is_the_first() -> None:
    held = Holding([("openhab", "b"), ("home_assistant", "z"), ("home_assistant", "a")])
    every = asyncio.run(ports.opened_all(held, "mail", 1))
    assert [(o.connection.kind, o.connection.label) for o in every] == [
        ("home_assistant", "a"), ("home_assistant", "z"), ("openhab", "b")]
    first = asyncio.run(ports.opened(held, "mail", 1))
    assert first is not None and first.connection.label == "a"


@pytest.mark.usefixtures("second_house")
def test_a_one_port_serves_from_the_first_connection_alone() -> None:
    held = Holding([("openhab", "b"), ("home_assistant", "z"), ("home_assistant", "a")])
    every = asyncio.run(ports.opened_all(held, "house", 1))
    assert [(o.connection.kind, o.connection.label) for o in every] == [("home_assistant", "a")]
    assert held.asked == [(held.held[2].id, None)]


class Off(SettingsReader):
    """A reader whose household has switched `ports` off on connection `connection`."""

    def __init__(self, connection: int, ports: set[str]) -> None:
        self._off = {connection: frozenset(ports)}

    async def ports_off(self, household_id: int) -> dict[int, frozenset[str]]:
        return self._off

    async def of(self, household_id: int, port: Port) -> dict[str, list[str]]:
        return {}

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        raise NotImplementedError

    async def history(self, connection_id: int, household_id: int, limit: int, before: int | None = None) -> tuple[Change, ...]:
        raise NotImplementedError


@pytest.mark.usefixtures("second_house")
def test_a_switched_off_port_is_as_if_the_connection_did_not_implement_it() -> None:
    held = Holding([("home_assistant", ""), ("openhab", "")])
    services.register(SettingsReader, Off(1, {"house"}))
    opened = asyncio.run(ports.opened(held, "house", 1))
    assert opened is not None and opened.connection.kind == "openhab"
    other = asyncio.run(ports.opened(held, "automations", 1))
    assert other is not None and other.connection.kind == "home_assistant"
    services.register(SettingsReader, Off(1, {"house"}))
    assert asyncio.run(ports.opened_all(Holding([("home_assistant", "")]), "house", 1)) == ()


def test_every_port_states_its_combine_rule() -> None:
    assert set(PORTS) == set(get_args(Port))


@pytest.mark.usefixtures("second_house")
def test_a_port_with_no_held_kind_is_none_and_a_person_is_passed_on() -> None:
    held = Holding([("sure", "")])
    assert asyncio.run(ports.opened(held, "house", 1, 7)) is None
    assert asyncio.run(ports.opened_all(held, "house", 1, 7)) == ()
    held = Holding([("home_assistant", "")])
    assert asyncio.run(ports.opened(held, "house", 1, 7)) is not None
    assert held.asked == [(1, 7)]
