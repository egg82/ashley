"""The House port's automation listing, wait and switch over the fake HA (`automations_support.FakeHouse`): each
automation names the thing it shows as, whether it is on and when it last ran, one written in YAML with no config id
included; `shown_as` waits for a written automation to appear; `set_enabled` turns one on or off, and any failure of
it is the house out of reach."""

import asyncio
from datetime import datetime

import pytest
from ashley.home_assistant.house import ConfigItem, HouseUnavailable
from automations_support import FakeHouse

TURN_OFF = ("POST", "/api/services/automation/turn_off")


def test_an_automation_lists_its_thing_whether_it_is_on_and_when_it_last_ran() -> None:
    fake = FakeHouse(yaml_only=["automation.from_yaml"])
    fake.add("arrive", "Arrival", on=False)
    got = {i.thing: i for i in asyncio.run(fake.house().configs("automation"))}
    ran = datetime.fromisoformat("2026-10-13T04:30:43.481239+00:00")
    assert got == {"automation.arrive": ConfigItem("arrive", "Arrival", "automation.arrive", False, ran),
                   "automation.from_yaml": ConfigItem(None, "automation.from_yaml", "automation.from_yaml", True, None)}


def test_a_written_automation_is_waited_for_until_the_house_shows_it() -> None:
    fake = FakeHouse(hidden_for=2)
    fake.add("ashley_bench_1_piece_1", "porch")
    assert asyncio.run(fake.house().shown_as("automation", "ashley_bench_1_piece_1")) == "automation.ashley_bench_1_piece_1"
    assert fake.requests.count(("GET", "/api/states")) == 3


def test_one_the_house_never_shows_is_none_after_the_tries() -> None:
    fake = FakeHouse(hidden_for=10)
    fake.add("ashley_bench_1_piece_1", "porch")
    assert asyncio.run(fake.house().shown_as("automation", "ashley_bench_1_piece_1")) is None
    assert fake.requests.count(("GET", "/api/states")) == 3


def test_set_enabled_turns_the_named_automation_on_or_off() -> None:
    fake = FakeHouse()
    first, second = fake.add("a", "A", on=True), fake.add("b", "B", on=False)
    house = fake.house()
    asyncio.run(house.set_enabled(first, False))
    asyncio.run(house.set_enabled(second, True))
    assert fake.enabled == {first: False, second: True}


@pytest.mark.parametrize("fake", [FakeHouse(failing={TURN_OFF: 500}), FakeHouse(failing={TURN_OFF: 400}),
                                  FakeHouse(down_after=0)])
def test_a_switch_the_house_does_not_carry_out_is_unavailable(fake: FakeHouse) -> None:
    with pytest.raises(HouseUnavailable, match="^turn_off: "):
        asyncio.run(fake.house().set_enabled("automation.a", False))
