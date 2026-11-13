"""`house.has_action(house, name)`: True when the house has the service, False when it can be read and has not, None
when that cannot be told (no house, out of reach, an answer that is not a service list). Her automation guidance says
what the house says, and the house is asked at most once for a turn."""

import asyncio
from typing import Any

import httpx2
import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.ha_house import HaHouse
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import ActionInfo, HouseUnavailable, NullHouse, has_action
from ashley.tools.bench_automation_specs import instructions
from ashley.tools.bench_automations import BenchAutomationTools
from automations_support import SETTINGS, FakeHouse
from homes_support import AnyHousehold
from bhb_support import World, pods, reply, switch_on
from contract.conversations_support import run

WAKE = "rest_command.ashley_wake"


def served(status: int = 200, body: Any = None, raw: bytes | None = None) -> HaHouse:
    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/services", "the service list is the only thing asked"
        return httpx2.Response(status, content=raw) if raw is not None else httpx2.Response(status, json=body)

    http = httpx2.AsyncClient(base_url="http://ha.test:8123", transport=httpx2.MockTransport(handle))
    return HaHouse(HomeAssistant(http), SETTINGS)


def test_a_house_with_the_service_says_true_and_one_without_says_false() -> None:
    assert asyncio.run(has_action(FakeHouse(wake=True).house(), WAKE)) is True
    assert asyncio.run(has_action(FakeHouse(wake=False).house(), WAKE)) is False
    assert asyncio.run(has_action(FakeHouse().house(), "automation.turn_on")) is True
    assert asyncio.run(has_action(FakeHouse().house(), "automation.no_such_service")) is False
    assert asyncio.run(has_action(FakeHouse().house(), "no_such_domain.turn_on")) is False


def test_the_answer_is_about_the_name_asked_not_about_the_house() -> None:
    house = FakeHouse(wake=True)
    assert asyncio.run(has_action(house.house(), WAKE)) is True
    assert asyncio.run(has_action(house.house(), "rest_command.other")) is False


def test_no_house_is_unknown_not_false() -> None:
    assert asyncio.run(has_action(NullHouse(), WAKE)) is None


def test_a_house_out_of_reach_is_unknown_not_false() -> None:
    assert asyncio.run(has_action(FakeHouse(wake=True, down_after=0).house(), WAKE)) is None
    assert asyncio.run(has_action(served(500, {"message": "boom"}), WAKE)) is None
    assert asyncio.run(has_action(served(401, {"message": "no"}), WAKE)) is None


@pytest.mark.parametrize("answer", [{"rest_command": {"ashley_wake": {}}}, "garbled", 3, None,
                                    [{"domain": "rest_command", "services": ["ashley_wake"]}],
                                    [{"domain": "rest_command", "services": "ashley_wake"}],
                                    [{"domain": "rest_command", "services": None}]])
def test_an_answer_that_is_not_a_service_list_is_unknown_not_false(answer: object) -> None:
    assert asyncio.run(has_action(served(200, answer), WAKE)) is None


def test_a_list_of_things_that_are_not_domains_is_unknown_not_false() -> None:
    """Scenario: a proxy in front of Home Assistant answers `/api/services` 200 with a JSON array of strings. The
    answer is not a service list, so the house is unknown, but it reads as False and her guidance then says this
    house lacks the wake rest command."""
    assert asyncio.run(has_action(served(200, [3, "x"]), WAKE)) is None


@pytest.mark.parametrize("name", ["", "nodot", "a.b.c"])
def test_a_name_that_is_not_a_domain_and_service_is_unknown_not_an_exception(name: str) -> None:
    """Scenario: a caller passes `rest_command` (or a name read from a config) to a wired house; it raises out of the
    caller's turn instead of answering None, which the interface gives for what cannot be told."""
    assert asyncio.run(has_action(FakeHouse(wake=True).house(), name)) is None


def test_a_body_that_is_not_json_is_unknown_not_false() -> None:
    assert asyncio.run(has_action(served(200, raw=b"<html>not home assistant</html>"), WAKE)) is None


def test_the_guidance_differs_for_each_of_wired_not_wired_and_unknown() -> None:
    texts = [instructions(True), instructions(False), instructions(None)]
    assert all(isinstance(t, str) and t for t in texts)
    assert len(set(texts)) == 3


class Counting(NullHouse):
    """A house that offers the wake action (`answer` True), offers another one only (False) or cannot be read (None),
    and counts how often its actions are asked."""

    def __init__(self, answer: bool | None) -> None:
        self.answer, self.asked = answer, 0

    def offered(self) -> bool:
        return True

    async def actions(self) -> tuple[ActionInfo, ...]:
        self.asked += 1
        if self.answer is None:
            raise HouseUnavailable("down")
        return (ActionInfo(WAKE if self.answer else "light.turn_on", "", {}, "none"),)


@pytest.mark.parametrize("answer", [True, False, None])
def test_her_guidance_carries_what_the_house_said_and_the_house_is_asked_once_for_a_turn(answer: bool | None) -> None:
    async def go() -> None:
        house = Counting(answer)
        services.register(Homes, AnyHousehold(house))
        try:
            tools = BenchAutomationTools(1, 2, 3)
            first, second, third = await tools.catalogue(), await tools.catalogue(), await tools.catalogue()
            assert first.instructions == second.instructions == third.instructions
            assert first.instructions is not None and instructions(answer) in first.instructions
            assert house.asked == 1, "unknown is remembered for the turn too"
            await BenchAutomationTools(1, 2, 3).catalogue()
            assert house.asked == 2, "a new turn asks again"
        finally:
            services.unregister(Homes)

    run(go())


def test_a_bench_turn_of_several_steps_asks_the_house_once(world: World) -> None:
    async def go() -> None:
        house = Counting(True)
        services.register(Homes, AnyHousehold(house))
        try:
            async with pods(world):
                world.model.play(switch_on("c1"), switch_on("c2"), switch_on("c3"), reply("done"))
                await respond(world.bench_say("do three things"))
                assert world.model.steps == 4
                assert house.asked == 1
        finally:
            services.unregister(Homes)

    run(go())
