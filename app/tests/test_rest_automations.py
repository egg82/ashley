"""The house's automations over HA's REST API, against a fake HA: listed by entity with their config ids, read and
written by id (a write answered with the entity once HA shows it), deleted, turned on and off; HA's refusal is
AutomationRejected with its own message, and a house out of reach is AutomationsUnavailable naming the step."""

import asyncio
from datetime import UTC, datetime

import pytest

from ashley.home_assistant.automations import (AutomationRejected, AutomationsUnavailable, NullAutomations)
from automations_support import FakeHouse


def test_listed_gives_each_automation_with_its_id_name_state_and_last_fired() -> None:
    house = FakeHouse(yaml_only=["automation.from_yaml"])
    house.add("7e9f", "Alana is home")
    house.add("65b3", "Welcome over Wi-Fi", on=False)
    listed = asyncio.run(house.client().listed())
    assert [(a.entity_id, a.automation_id, a.alias, a.enabled) for a in listed] == [
        ("automation.65b3", "65b3", "Welcome over Wi-Fi", False), ("automation.7e9f", "7e9f", "Alana is home", True),
        ("automation.from_yaml", None, "automation.from_yaml", True)]
    assert listed[0].last_triggered == datetime(2026, 10, 13, 4, 30, 43, 481239, tzinfo=UTC)
    assert listed[2].last_triggered is None


def test_config_reads_one_by_id_and_none_for_an_id_the_house_does_not_have() -> None:
    house = FakeHouse()
    house.add("7e9f", "Alana is home", triggers=[{"trigger": "state"}])
    assert asyncio.run(house.client().config("7e9f")) == {"id": "7e9f", "alias": "Alana is home",
                                                          "triggers": [{"trigger": "state"}]}
    assert asyncio.run(house.client().config("nope")) is None


def test_write_creates_and_answers_its_entity_once_it_shows() -> None:
    house = FakeHouse(hidden_for=2)
    entity = asyncio.run(house.client().write("ashley_bench_1_piece_2", {"alias": "a"}))
    assert entity == "automation.ashley_bench_1_piece_2"
    assert house.configs["ashley_bench_1_piece_2"] == {"id": "ashley_bench_1_piece_2", "alias": "a"}


def test_write_answers_none_when_the_entity_never_shows_in_time() -> None:
    house = FakeHouse(hidden_for=10)
    assert asyncio.run(house.client().write("ashley_bench_1_piece_2", {"alias": "a"})) is None


def test_a_refused_config_is_rejected_with_has_message_and_nothing_written() -> None:
    house = FakeHouse(refuse="Message malformed: required key not provided @ data['triggers']")
    with pytest.raises(AutomationRejected) as refused:
        asyncio.run(house.client().write("x", {"alias": "a"}))
    assert refused.value.message.startswith("Message malformed")
    assert house.configs == {}


def test_delete_answers_whether_there_was_one() -> None:
    house = FakeHouse()
    house.add("x", "a")
    assert asyncio.run(house.client().delete("x")) is True
    assert asyncio.run(house.client().delete("x")) is False
    assert house.configs == {}


def test_set_enabled_turns_an_automation_off_and_on() -> None:
    house = FakeHouse()
    entity = house.add("x", "a")
    asyncio.run(house.client().set_enabled(entity, False))
    assert house.enabled[entity] is False
    asyncio.run(house.client().set_enabled(entity, True))
    assert house.enabled[entity] is True
    assert ("POST", "/api/services/automation/turn_on") in house.writes


def test_a_house_out_of_reach_is_unavailable_naming_the_step() -> None:
    house = FakeHouse(down_after=0)
    with pytest.raises(AutomationsUnavailable, match="^list: ConnectError$"):
        asyncio.run(house.client().listed())
    with pytest.raises(AutomationsUnavailable, match="^write"):
        asyncio.run(house.client().write("x", {}))


def test_an_unwired_house_offers_nothing_and_every_call_is_unavailable() -> None:
    null = NullAutomations()
    assert null.offered() is False
    with pytest.raises(AutomationsUnavailable):
        asyncio.run(null.listed())
    with pytest.raises(AutomationsUnavailable):
        asyncio.run(null.write("x", {}))


def test_has_service_says_whether_the_house_has_the_wake_rest_command() -> None:
    assert asyncio.run(FakeHouse(wake=True).client().has_service("rest_command.ashley_wake")) is True
    assert asyncio.run(FakeHouse(wake=False).client().has_service("rest_command.ashley_wake")) is False


@pytest.mark.parametrize("services", ["garbled", ["a", "b"], None, 3])
def test_has_service_is_unknown_not_false_when_the_domain_answers_no_object_of_services(services: object) -> None:
    house = FakeHouse(services=[{"domain": "rest_command", "services": services}])
    assert asyncio.run(house.client().has_service("rest_command.ashley_wake")) is None


def test_has_service_is_false_when_the_domain_is_missing_or_lacks_the_service() -> None:
    assert asyncio.run(FakeHouse(services=[{"domain": "light", "services": {}}]).client().has_service(
        "rest_command.ashley_wake")) is False
    assert asyncio.run(FakeHouse(services=[{"domain": "rest_command", "services": {"x": {}}}]).client().has_service(
        "rest_command.ashley_wake")) is False


@pytest.mark.parametrize("name", ["", "nodot", "a.b.c"])
def test_a_name_that_is_not_a_domain_and_service_is_unknown_not_an_exception(name: str) -> None:
    assert asyncio.run(FakeHouse(wake=True).client().has_service(name)) is None


@pytest.mark.parametrize("services", [[3, "x"], [{"domain": 3, "services": {}}], [{"services": {}}]])
def test_a_list_of_things_that_are_not_domains_is_unknown_not_false(services: object) -> None:
    assert asyncio.run(FakeHouse(services=services).client().has_service("rest_command.ashley_wake")) is None


def test_has_service_is_unknown_not_false_when_the_house_cannot_be_reached_or_the_wired_house_is_null() -> None:
    assert asyncio.run(FakeHouse(wake=True, down_after=0).client().has_service("rest_command.ashley_wake")) is None
    assert asyncio.run(NullAutomations().has_service("rest_command.ashley_wake")) is None
