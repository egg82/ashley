"""`house_state` shows when an entity's state last changed, as `ashley.stamp.stamp` in the household's zone, and shows
nothing for it when the house gives no time or the household's zone cannot be had."""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from ashley import services
from ashley.home_assistant.house import State
from ashley.inference.model import ToolCall
from ashley.people.model import Household
from ashley.people.people import People
from ashley.home_assistant import irreversible
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_act import Rules
from ashley.tools.house_state import HouseStateTools
from ashley.tools.house_tools import HouseTools
from house_double_support import MemoryHouse, state
from one_home_support import OneHome

CONFIG = house_state_config.load()
HOUSEHOLD = 7


@pytest.fixture
def denver() -> Iterator[None]:
    services.register(People, OneHome(Household(HOUSEHOLD, "home", "America/Denver", "", ())))
    yield
    services.unregister(People)


def _read(things: list[State], **arguments: object) -> list[dict[str, Any]]:
    tool = HouseStateTools(MemoryHouse(things=things), CONFIG, HOUSEHOLD)
    result = asyncio.run(tool.call(ToolCall("c1", "house_state", arguments)))
    assert not result.is_error, result.content
    listed: list[dict[str, Any]] = json.loads(result.content)["entities"]
    return listed


def _door(changed: datetime | None) -> State:
    return replace(state("binary_sensor.d1", "Test Door", "on", "Hall"), changed=changed)


@pytest.mark.parametrize(("changed", "shown"), [
    (datetime(2026, 10, 31, 20, 0, tzinfo=UTC), "Sat 31 Oct 2026 14:00"),   # MDT, UTC-6
    (datetime(2026, 11, 1, 9, 0, tzinfo=UTC), "Sun 1 Nov 2026 02:00"),      # after DST ended at 08:00 UTC, UTC-7
    (datetime(2026, 11, 1, 6, 59, tzinfo=UTC), "Sun 1 Nov 2026 00:59"),     # before it, UTC-6
])
def test_changed_is_the_household_local_stamp(denver: None, changed: datetime, shown: str) -> None:
    [door] = _read([_door(changed)], domain="binary_sensor")
    assert door["changed"] == shown and door["state"] == "on"


@pytest.mark.usefixtures("denver")
def test_no_changed_time_shows_no_changed_field() -> None:
    [door] = _read([_door(None)], domain="binary_sensor")
    assert "changed" not in door and "None" not in json.dumps(door)


def test_an_unreachable_zone_shows_no_changed_field() -> None:
    [door] = _read([_door(datetime(2026, 11, 1, 9, 0, tzinfo=UTC))], domain="binary_sensor")
    assert "changed" not in door


@pytest.mark.usefixtures("denver")
def test_every_entity_in_a_list_carries_its_own_time() -> None:
    things = [replace(_door(datetime(2026, 11, 1, 9, 0, tzinfo=UTC)), id="binary_sensor.a", name="A Door"),
              replace(_door(None), id="binary_sensor.b", name="B Door")]
    got = {e["names"]: e.get("changed") for e in _read(things, domain="binary_sensor")}
    assert got == {"A Door": "Sun 1 Nov 2026 02:00", "B Door": None}


@pytest.mark.usefixtures("denver")
def test_the_house_tools_read_carries_it_for_the_household_they_serve() -> None:
    house = MemoryHouse(things=[_door(datetime(2026, 11, 1, 9, 0, tzinfo=UTC))])
    tools = HouseTools(house, Rules((), (), irreversible.load()), house_look_config.load(),
                       CONFIG, "", HOUSEHOLD)
    result = asyncio.run(tools.call(ToolCall("c1", "house_state", {"name": "door"})))
    assert json.loads(result.content)["entities"][0]["changed"] == "Sun 1 Nov 2026 02:00"
