"""A wake rule that names a paired kiosk of its household (`device`): the field is checked by shape and may not be
given with a speaker; the runner runs the turn on the kiosk's thread, queued in the outbox for `announce`; a device that
is not a screen of the rule's household leaves the turn on the phone."""

import json

import pytest
from ashley.channels.kiosk.announce import is_screen
from ashley.channels.model import Device, Listed
from ashley.channels.outbox import Outbox
from ashley import services
from ashley.workshop.wake_rule import WakeRule, rule_of
from contract.conversations_support import household, run, scalar
from contract.test_inflight_resume import World
from house_double_support import MemoryHouse, state
from homes_support import AnyHousehold
from ashley.home_assistant.homes import Homes
from wb_runner_support import DONE, GREET, stack, sweep
from wb_support import add_device

BASE = {"event": "arrived", "brief": GREET, "tools": ["lamp_on"]}
KITCHEN = "media_player.zq_kitchen"


def body(**extra: object) -> str:
    return json.dumps({**BASE, **extra})


def test_a_rule_may_name_a_device_by_its_id() -> None:
    rule = rule_of(body(device=12))
    assert isinstance(rule, WakeRule) and rule.device == 12
    plain = rule_of(body())
    assert plain is not None and plain.device is None and rule.specificity == plain.specificity == 0


@pytest.mark.parametrize("given", [0, -3, "12", 1.5, True, None, [12]])
def test_a_device_that_is_not_a_positive_id_makes_no_rule(given: object) -> None:
    assert rule_of(body(device=given)) is None


def test_a_rule_naming_a_speaker_and_a_device_makes_no_rule() -> None:
    assert rule_of(body(speaker=KITCHEN)) is not None and rule_of(body(device=12)) is not None
    assert rule_of(body(speaker=KITCHEN, device=12)) is None


def listing(world: World) -> tuple[dict[int, list[Listed]], Device, Device]:
    household = world.who.household_id
    kiosk = Device(add_device(world.url, household, "zq-kiosk", "tablet"), household, "tablet", "Hallway", "present",
                   "text", "chat")
    ha = Device(add_device(world.url, household, "zq-ha", "ha", house=True), household, "ha", "house", "present",
                "text", "chat")
    return {household: [Listed(ha, "house"), Listed(kiosk, "other")]}, kiosk, ha


def queued(world: World) -> list[str]:
    return list(scalar(world.url, "SELECT coalesce(json_agg(thread ORDER BY id), '[]') FROM outbox"))


def test_a_wake_whose_rule_names_a_kiosk_runs_on_its_thread_for_announce(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    services.register(Homes, AnyHousehold(MemoryHouse(things=[state(KITCHEN, KITCHEN, "idle")])))

    async def go() -> None:
        rows, kiosk, _ = listing(world)
        async with stack(world, rows=rows) as s:
            await s.rule(body=body(device=kiosk.id))
            wake = await s.hand_in()
            await sweep()
            assert s.outcome(wake) == "turn"
            assert queued(world) == [f"device:{kiosk.id}"]
            (waiting,) = await services.get(Outbox).take("device:")
            assert await is_screen(world.who.household_id, kiosk.id) and waiting.thread == f"device:{kiosk.id}"
            assert "where others may hear or see it" in str(world.first.inference.prompts[0])

    run(go())


@pytest.mark.parametrize("which", ["gone", "house_device", "other_household"])
def test_a_device_that_is_not_a_kiosk_of_the_household_leaves_the_turn_on_the_phone(world: World, which: str) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        rows, _, ha = listing(world)
        other = 0
        if which == "other_household":
            away = household(world.url, "away")
            other = add_device(world.url, away, "zq-away", "away")
            rows[away] = [Listed(Device(other, away, "away", "Hallway", "present", "text", "chat"), "other")]
        named = {"gone": 99999, "house_device": ha.id, "other_household": other}[which]
        async with stack(world, rows=rows) as s:
            await s.rule(body=body(device=named))
            wake = await s.hand_in()
            await sweep()
            assert s.outcome(wake) == "turn"
            assert queued(world) == [f"push:{world.who.id}"]

    run(go())
