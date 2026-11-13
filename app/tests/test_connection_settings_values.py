"""What a kind's settings allow (`ashley.connections.settings.validate`), Home Assistant's declared schema, and how her house
tools take a household's settings: once per turn, and none at all is the least trust."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from ashley import services
from ashley.connections.model import Port
from ashley.connections.settings import (EntityListPerAction, SettingsInvalid, SettingValue, SettingValues, validate)
from ashley.connections.settings_read import Change, SettingsReader, StoredSettings
from ashley.home_assistant import house_values
from ashley.home_assistant.house import ActionInfo
from ashley.home_assistant.house_values import HouseValues
from ashley.home_assistant.kind import HOME_ASSISTANT
from ashley.inference.model import ToolCall
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from house_double_support import MemoryHouse, state
from house_settings_support import VALUES, house_rules
from outside_record_support import MemoryRecord
from ashley.senses.outside_record import OutsideRecord

SETTINGS = HOME_ASSISTANT.settings


def bad(values: Mapping[str, Any]) -> tuple[str, str]:
    with pytest.raises(SettingsInvalid) as refused:
        validate(SETTINGS, values)
    return refused.value.key, refused.value.reason


def test_home_assistant_declares_three_trust_settings_one_that_judges_and_one_preference() -> None:
    assert {s.key: s.decides for s in SETTINGS} == {
        "household_reads": "taint", "service_reads": "taint", "reads": "read", "consequential_entities": "tier",
        "glance_calendars": "plain"}
    assert isinstance(next(s for s in SETTINGS if s.key == "household_reads").field, EntityListPerAction)


def test_a_value_of_the_declared_shape_is_stored_as_given() -> None:
    values: dict[str, SettingValue] = {"household_reads": {"todo.get_items": ["todo.a"]}, "reads": ["script.a", "script.b"]}
    assert validate(SETTINGS, values) == values


def test_a_list_is_deduplicated_in_order_and_an_empty_one_is_dropped() -> None:
    assert validate(SETTINGS, {"reads": ["script.b", "script.a", "script.b"], "service_reads": []}) == {"reads": ["script.b", "script.a"]}
    assert validate(SETTINGS, {"household_reads": {"todo.get_items": []}}) == {}


@pytest.mark.parametrize(("values", "expected"), [
    ({"colour": ["a.b"]}, ("colour", "unknown_key")),
    ({"reads": "script.a"}, ("reads", "wrong_shape")),
    ({"reads": {"script.a": ["x.y"]}}, ("reads", "wrong_shape")),
    ({"household_reads": ["todo.a"]}, ("household_reads", "wrong_shape")),
    ({"reads": ["script"]}, ("reads", "bad_id")),
    ({"reads": ["Script.A"]}, ("reads", "bad_id")),
    ({"reads": [1]}, ("reads", "bad_id")),
    ({"reads": ["a.b.c"]}, ("reads", "bad_id")),
    ({"household_reads": {"todo.other_action": ["todo.a"]}}, ("household_reads", "bad_id")),
    ({"household_reads": {"todo.get_items": ["nope"]}}, ("household_reads", "bad_id")),
    ({"reads": [f"script.s{i}" for i in range(201)]}, ("reads", "too_many"))])
def test_a_value_the_schema_does_not_allow_is_refused_naming_its_key(values: Mapping[str, Any], expected: tuple[str, str]) -> None:
    assert bad(values) == expected


def test_exactly_the_largest_list_is_allowed() -> None:
    assert len(validate(SETTINGS, {"reads": [f"script.s{i}" for i in range(200)]})["reads"]) == 200


def test_the_settings_are_read_as_the_tools_take_them_and_a_malformed_value_is_empty() -> None:
    got = house_values.of({"household_reads": {"todo.get_items": ["todo.a"]}, "service_reads": ["weather.x"], "reads": ["script.a"],
                           "consequential_entities": ["switch.relay"], "glance_calendars": ["calendar.a"]})
    assert got == HouseValues({"todo.get_items": ("todo.a",)}, ("weather.x",), ("script.a",), ("switch.relay",), ("calendar.a",))
    assert house_values.of({"household_reads": ["todo.a"], "reads": {"x": ["y.z"]}}) == HouseValues()
    assert house_values.of({}) == HouseValues()


class Reading(SettingsReader):
    """Answers `values` as the household's settings, counting how often it was asked."""

    def __init__(self, values: SettingValues) -> None:
        self.values, self.asked = values, 0

    async def of(self, household_id: int, port: Port) -> SettingValues:
        self.asked += 1
        return self.values

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        raise AssertionError("not read here")

    async def history(self, connection_id: int, household_id: int, limit: int, before: int | None = None) -> tuple[Change, ...]:
        raise AssertionError("not read here")


def tools(house: MemoryHouse) -> HouseTools:
    services.register(OutsideRecord, MemoryRecord())
    return HouseTools(house, house_rules(HouseValues()), house_look_config.load(), house_state_config.load(), "", 1,
                      values=lambda: house_values.read(1))


def a_house() -> MemoryHouse:
    house = MemoryHouse(things=[state("todo.inbox", "Inbox", "1"), state("switch.relay", "Relay", "off"),
                                state("light.den", "Den", "off")])
    house.catalogue = [ActionInfo("todo.get_items", "Items", {}, "only"), ActionInfo("switch.turn_on", "On", {}, "none")]
    house.returns = {"todo.get_items": {"todo.inbox": {"items": []}}}
    return house


def asked(turn: object, tool: str, **arguments: object) -> bool:
    """Whether the answer to the call is outside words: `house_ask`'s answer is, unless it says it is not."""
    assert isinstance(turn, HouseTools)
    return asyncio.run(turn.call(ToolCall("c", tool, arguments))).outside is not False


def test_with_no_settings_a_list_read_is_outside_words() -> None:
    services.register(SettingsReader, Reading({}))
    turn = asyncio.run(tools(a_house()).for_turn())
    assert asked(turn, "house_ask", action="todo.get_items", ids=["todo.inbox"])


def test_with_the_list_set_the_same_read_is_the_household_s_own_words() -> None:
    services.register(SettingsReader, Reading({"household_reads": {"todo.get_items": ["todo.inbox"]}}))
    turn = asyncio.run(tools(a_house()).for_turn())
    assert not asked(turn, "house_ask", action="todo.get_items", ids=["todo.inbox"])


def test_a_tools_not_bound_to_a_turn_trusts_nothing() -> None:
    services.register(SettingsReader, Reading({"household_reads": {"todo.get_items": ["todo.inbox"]}}))
    assert asked(tools(a_house()), "house_ask", action="todo.get_items", ids=["todo.inbox"])


def test_a_turn_reads_the_settings_once_and_keeps_that_version_while_they_change() -> None:
    reading = Reading({"household_reads": {"todo.get_items": ["todo.inbox"]}})
    services.register(SettingsReader, reading)
    turn = asyncio.run(tools(a_house()).for_turn())
    reading.values = {}
    assert not asked(turn, "house_ask", action="todo.get_items", ids=["todo.inbox"]), "still the version the turn read"
    assert not asked(turn, "house_ask", action="todo.get_items", ids=["todo.inbox"])
    assert reading.asked == 1
    assert asked(asyncio.run(tools(a_house()).for_turn()), "house_ask", action="todo.get_items", ids=["todo.inbox"]), "the next turn sees them"
    assert reading.asked == 2


def test_a_listed_consequential_entity_is_judged_in_the_turn_that_read_it_and_not_before() -> None:
    services.register(SettingsReader, Reading({"consequential_entities": ["switch.relay"]}))
    call = ToolCall("c", "house_do", {"action": "switch.turn_on", "ids": ["switch.relay"]})
    base = tools(a_house())
    assert asyncio.run(base.tier(call)) == "runs"
    assert asyncio.run(asyncio.run(base.for_turn()).tier(call)) == "judged"


def test_settings_that_were_read_do_not_leak_into_the_shared_tools() -> None:
    services.register(SettingsReader, Reading({"service_reads": ["weather.get_forecasts"]}))
    base = tools(a_house())
    asyncio.run(base.for_turn())
    assert asked(base, "house_ask", action="todo.get_items", ids=["todo.inbox"])


def test_the_values_the_tests_use_are_what_the_migration_seeds() -> None:
    assert VALUES.household_reads["todo.get_items"] == ("todo.inbox", "todo.groceries", "todo.weekly_shopping")
