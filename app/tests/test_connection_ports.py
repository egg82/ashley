"""Opening a connection by port: the first visible connection of a kind of the port, in kind registration order, then
label, then id."""

import asyncio
import dataclasses
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.connections import ports
from ashley.connections.connections import NullConnections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Connection, Kind, Opened
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


@pytest.mark.usefixtures("second_house")
def test_within_a_kind_the_label_orders_and_all_are_listed() -> None:
    held = Holding([("openhab", "b"), ("home_assistant", "z"), ("home_assistant", "a")])
    every = asyncio.run(ports.opened_all(held, "house", 1))
    assert [(o.connection.kind, o.connection.label) for o in every] == [
        ("home_assistant", "a"), ("home_assistant", "z"), ("openhab", "b")]
    first = asyncio.run(ports.opened(held, "house", 1))
    assert first is not None and first.connection.label == "a"


@pytest.mark.usefixtures("second_house")
def test_a_port_with_no_held_kind_is_none_and_a_person_is_passed_on() -> None:
    held = Holding([("sure", "")])
    assert asyncio.run(ports.opened(held, "house", 1, 7)) is None
    assert asyncio.run(ports.opened_all(held, "house", 1, 7)) == ()
    held = Holding([("home_assistant", "")])
    assert asyncio.run(ports.opened(held, "house", 1, 7)) is not None
    assert held.asked == [(1, 7)]
