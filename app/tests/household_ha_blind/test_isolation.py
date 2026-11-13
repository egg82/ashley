"""One household's turn reaches only that household's Home Assistant: her house tools, presence, the room speaker, the
kiosk controls and the bench automations each go to the house of the household they were asked for, with its token,
and a household with no house reaches none (and never the env's)."""

import asyncio
from collections.abc import Coroutine, Generator
from typing import Any

import pytest
from ashley import services
from ashley.channels.kiosk import controls
from ashley.channels.kiosk.controls import Control
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Home, Homes, house_of
from ashley.home_assistant.media_player import play_for
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account
from ashley.people.people import People
from ashley.senses.homes_presence import HomesPresence
from ashley.tools import home_assistant_config, house_look_config, house_state_config
from ashley.home_assistant import irreversible
from ashley.tools.everyday import Everyday, HomesEveryday, HouseholdTools
from ashley.tools.house_act import Rules
from ashley.tools.house_tools import HouseTools
from ashley.tools.tools import Catalogue, Tools
from hha_blind_support import A_TOKEN, A_URL, B_TOKEN, B_URL, CONFIG, ENV, FakeHouses, HeldConnections
from connection_legacy_support import remove_of

A, B, NONE = 2, 3, 4
A_HOST, B_HOST = "a-house.test:8123", "b-house.test:8123"


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(asyncio.wait_for(coro, 20))


class Mapped(People):
    """Everyone is mapped to `person.pat` on Home Assistant, as person 10 + household."""

    async def household(self, household_id: int) -> None:
        return None

    async def person_for(self, system: str, external_id: str) -> None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        if system != "home_assistant":
            return ()
        return (Account(1, household_id, 10 + household_id, system, "person.pat"),)


class Web(Tools):
    """The look-up every household has, house or none."""

    @classmethod
    def null(cls) -> "Web":
        return cls()

    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("web_search", "search", {"type": "object", "properties": {}}, True),), "")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "no such tool", True)


HALL = Control("hall-off", "Hall off", "light.turn_off", "light.l0")

class World:
    def __init__(self) -> None:
        self.houses = FakeHouses(lights=("Hall",))
        self.held = HeldConnections()
        self.held.connect(A, A_URL, A_TOKEN)
        self.held.connect(B, B_URL, B_TOKEN)
        self.homes = ConnectedHomes(self.held, CONFIG, self.houses.connect, env=ENV, house=self.houses.house)
        house = home_assistant_config.load()
        services.register(Homes, self.homes)
        services.register(Tools, Web())
        rules = Rules(house.excluded, (), irreversible.load())

        def build(home: Home) -> Tools:
            return HouseTools(home.house, rules, house_look_config.load(), house_state_config.load(), house.guidance)
        services.register(Everyday, HomesEveryday(build))

    def reached(self) -> set[str]:
        return {h for h in self.houses.hosts() if h}

    def forget(self) -> None:
        self.houses.seen.clear()


@pytest.fixture
def world() -> Generator[World]:
    w = World()
    yield w
    services.unregister(Everyday)
    services.unregister(Tools)


def _turn_on(call_id: str, name: str) -> ToolCall:
    return ToolCall(call_id, "house_do", {"action": "light.turn_on", "name": name})


def only(world: World, host: str, token: str) -> None:
    assert world.houses.seen, "nothing reached any house"
    assert world.reached() == {host}
    assert {b for _, _, _, b in world.houses.seen} == {f"Bearer {token}"}


def test_her_house_tools_list_only_the_turns_house(world: World) -> None:
    for household, host, token, other in ((A, A_HOST, A_TOKEN, "only_b_house_test"),
                                          (B, B_HOST, B_TOKEN, "only_a_house_test")):
        world.forget()
        listed = run(HouseholdTools(household).catalogue()).instructions or ""
        assert other not in listed and "only_" in listed
        only(world, host, token)


def test_her_house_tools_act_on_only_the_turns_house(world: World) -> None:
    world.forget()
    result = run(HouseholdTools(A).call(_turn_on("1", "only_a_house_test")))
    assert not result.is_error and "only_a_house_test" in result.content and "b_house" not in result.content
    only(world, A_HOST, A_TOKEN)
    world.forget()
    result = run(HouseholdTools(B).call(_turn_on("2", "only_b_house_test")))
    assert "only_b_house_test" in result.content
    only(world, B_HOST, B_TOKEN)


def test_a_household_with_no_house_has_no_house_tools_and_reaches_none(world: World) -> None:
    world.forget()
    names = {s.name for s in run(HouseholdTools(NONE).catalogue()).specs}
    assert not any(n.startswith("house_") for n in names)
    result = run(HouseholdTools(NONE).call(_turn_on("1", "only_a_house_test")))
    assert result.is_error
    assert world.houses.seen == []


def test_everyday_of_a_household_never_answers_with_another_households_tools(world: World) -> None:
    a, b = run(services.get(Everyday).of(A)), run(services.get(Everyday).of(B))
    assert a is not b
    assert "only_a_house_test" in (run(a.catalogue()).instructions or "")
    assert "only_b_house_test" in (run(b.catalogue()).instructions or "")


def test_a_replaced_connection_is_followed_on_the_next_call(world: World) -> None:
    run(HouseholdTools(A).catalogue())
    world.held.connect(A, B_URL, "fresh-token")
    world.forget()
    result = run(HouseholdTools(A).call(_turn_on("1", "only_b_house_test")))
    assert "only_b_house_test" in result.content
    assert world.reached() == {B_HOST} and {b for _, _, _, b in world.houses.seen} == {"Bearer fresh-token"}


def test_a_removed_connection_stops_her_house_tools(world: World) -> None:
    run(HouseholdTools(A).catalogue())
    run(remove_of(world.held, A, "home_assistant"))
    world.forget()
    assert not any(s.name.startswith("house_") for s in run(HouseholdTools(A).catalogue()).specs)
    assert world.houses.seen == []


def test_presence_reads_each_households_own_house(world: World) -> None:
    world.houses.states = {"a-house.test": "home", "b-house.test": "not_home"}
    presence = HomesPresence(Mapped())
    world.forget()
    assert run(presence.home(A)) == frozenset({10 + A})
    only(world, A_HOST, A_TOKEN)
    world.forget()
    assert run(presence.home(B)) == frozenset()
    only(world, B_HOST, B_TOKEN)


def test_presence_of_a_household_with_no_house_is_unknown_and_asks_no_house(world: World) -> None:
    world.forget()
    assert run(HomesPresence(Mapped()).home(NONE)) is None
    assert world.houses.seen == []


def test_presence_of_a_household_whose_house_is_down_is_unknown_not_another_households(world: World) -> None:
    world.houses.down.add("a-house.test")
    world.forget()
    assert run(HomesPresence(Mapped()).home(A)) is None
    assert world.reached() <= {A_HOST}


def test_the_room_speaker_plays_in_the_turns_house(world: World) -> None:
    world.forget()
    run(play_for(B, "media_player.kitchen", "http://ashley.test/say.mp3"))
    only(world, B_HOST, B_TOKEN)
    world.forget()
    run(play_for(A, "media_player.kitchen", "http://ashley.test/say.mp3"))
    only(world, A_HOST, A_TOKEN)


def test_the_room_speaker_of_a_household_with_no_house_falls_back_and_asks_no_house(world: World) -> None:
    world.forget()
    assert run(play_for(NONE, "media_player.kitchen", "http://ashley.test/say.mp3")) is False
    assert world.houses.seen == []


def test_kiosk_controls_run_in_the_devices_household(world: World) -> None:
    control = HALL
    world.forget()
    assert run(controls.run(control, 7, A)) is True
    only(world, A_HOST, A_TOKEN)
    world.forget()
    assert run(controls.run(control, 8, B)) is True
    only(world, B_HOST, B_TOKEN)


def test_a_kiosk_control_in_a_household_with_no_house_fails_and_reaches_none(world: World) -> None:
    world.forget()
    assert run(controls.run(HALL, 9, NONE)) is False
    assert world.houses.seen == []


def test_the_bench_automations_are_the_turns_houses(world: World) -> None:
    for household, host, token in ((A, A_HOST, A_TOKEN), (B, B_HOST, B_TOKEN)):
        world.forget()
        house = run(house_of(household))
        assert run(_listed(house)) is not None
        only(world, host, token)


async def _listed(house: Any) -> object:
    try:
        return await house.configs("automation")
    except Exception as e:
        return e


def test_the_bench_automations_of_a_household_with_no_house_are_not_offered_and_ask_no_house(world: World) -> None:
    world.forget()
    house = run(house_of(NONE))
    assert house.offered() is False
    assert world.houses.seen == []
