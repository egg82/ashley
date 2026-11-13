"""Initiative over a real house wake, through `runner.sweep()` and the shared turn loop: the moment gathered before the
turn (`channels.wake.moment`), the plan's instruction in her prompt, a recent greeting of the same event (a quiet one
included) keeping the next one quiet, what `Wakes.said_before` reads of her wake turns, the decision's log line, and the
moment surviving a checkpoint."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley import logs, services
from ashley.channels.checkpoint import dumps, loads
from ashley.channels.respond import respond
from ashley.channels.unprompted import QUIET
from ashley.channels.wake import moment as wake_moment
from ashley.channels.wake import wake_turn
from ashley.initiative.initiative import Scored
from ashley.initiative.moment import Moment, Outcome
from ashley.initiative.score import roll
from ashley.initiative.weights import parse
from ashley.senses.presence import Presence
from ashley.workshop.wake_rule import WakeRule
from contract.conversations_support import events, run, scalar
from contract.test_inflight_resume import World
from inflight_blind.ifb_checkpoint_support import checkpoint
from initiative_support import FLOOR, weights
from wb_runner_support import DONE, GREET, SILENT, stack, sweep
from wb_support import wake

HERS = DONE.text


def always(outcome: Outcome) -> Scored:
    odds = {"full": 0.0, "short": 0.0, "silent": 0.0, outcome: 1.0}
    return Scored(parse(weights(odds=[{"from": FLOOR, **odds}])))


def greeted_quiets() -> Scored:
    return Scored(parse(weights(threshold=0.0, greeted={"weight": -5.0, "within_s": 3600},
                                odds=[{"from": 0.0, "full": 1.0, "short": 0.0, "silent": 0.0}])))


def instruction(world: World, outcome: Outcome) -> str:
    return wake_turn.note(WakeRule("arrived", GREET, ()), world.who, wake(world.who.household_id), outcome).splitlines()[-1]


def answered_at(world: World, wake_id: int) -> Any:
    return scalar(world.url, "SELECT a.at FROM turns h JOIN turns a ON a.answers = h.id WHERE h.source = %s",
                  (f"wake:{wake_id}",))


@pytest.mark.parametrize("outcome", ["full", "short", "silent"])
def test_her_prompt_carries_the_plans_instruction_and_a_silent_plan_keeps_her_reply_quiet(
        world: World, outcome: Outcome) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world, always(outcome)) as s:
            await s.rule()
            await s.hand_in()
            await sweep()
            assert s.queued() == (0 if outcome == "silent" else 1)

    run(go())
    (prompt,) = world.first.inference.prompts
    seen = repr(prompt.messages)
    assert [instruction(world, o) in seen for o in ("full", "short", "silent")] == [o == outcome for o in
                                                                                   ("full", "short", "silent")]
    assert world.hers() == ([QUIET] if outcome == "silent" else [HERS])


def test_a_greeting_soon_after_the_last_is_quiet_even_when_the_last_was_quiet(world: World) -> None:
    world.first.inference.script = [SILENT, DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world, greeted_quiets()) as s:
            await s.rule()
            await s.rule(event="left")
            await s.hand_in("ctx-1")
            await sweep()
            await s.hand_in("ctx-2")
            await sweep()
            await s.hand_in("ctx-3", event="left")
            await sweep()
            assert s.queued() == 1

    run(go())
    assert world.hers() == [QUIET, QUIET, HERS], "the third, another event, is the control that DONE goes out"
    assert instruction(world, "silent") in repr(world.first.inference.prompts[1].messages)


def test_said_before_reads_her_wake_turns_quiet_ones_as_greeted_and_not_as_spoken(world: World) -> None:
    world.first.inference.script = [DONE, SILENT, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.rule(event="left")
            spoke = await s.hand_in("ctx-1")
            await sweep()
            quiet = await s.hand_in("ctx-2", event="left")
            await sweep()
            first = await s.wakes.said_before(await s.hand_in("ctx-3"), world.who.id)
            assert first.heard_at is None
            await respond(world.inbound())
            arrived = await s.wakes.said_before(await s.hand_in("ctx-4"), world.who.id)
            left = await s.wakes.said_before(await s.hand_in("ctx-5", event="left"), world.who.id)
            heard = scalar(world.url, "SELECT max(at) FROM turns WHERE author = 'person'")
            assert (arrived.heard_at, arrived.greeted_at, arrived.spoke_at) == (
                heard, answered_at(world, spoke), answered_at(world, spoke))
            assert (left.greeted_at, left.spoke_at) == (answered_at(world, quiet), answered_at(world, spoke))
            assert answered_at(world, quiet) > answered_at(world, spoke), "control: the quiet turn is the later one"
            assert await s.wakes.said_before(10**9, world.who.id) == type(first)(None, None, None)

    run(go())


class TwoHome(Presence):
    def __init__(self, ids: frozenset[int]) -> None:
        self.ids = ids

    async def home(self, household_id: int) -> frozenset[int] | None:
        return self.ids


def test_the_moment_is_measured_from_the_event_in_the_households_zone(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            first = await s.hand_in("ctx-1")
            await sweep()
            services.register(Presence, TwoHome(frozenset({world.who.id, 999, 998})))
            second = await s.hand_in("ctx-2")
            event = wake(world.who.household_id, "ctx-2", at=datetime(2026, 11, 13, 3, 30, tzinfo=UTC))
            got = await wake_moment.gathered(second, event, world.who)
            assert got.seed == f"wake:{second}" and got.hour == 20 and got.others_home == 2
            last = answered_at(world, first)
            assert got.since_greeted_s == pytest.approx((event.at - last).total_seconds())
            assert got.since_spoke_s == got.since_greeted_s and got.since_heard_s is None

    run(go())


def test_the_decision_is_logged_with_its_score_roll_and_outcome_and_never_her_words(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    policy = Scored(parse(weights(odds=[{"from": FLOOR, "full": 0.5, "short": 0.5, "silent": 0.0}])))

    ids: list[int] = []

    async def go() -> None:
        async with stack(world, policy) as s:
            await s.rule()
            ids.append(await s.hand_in())
            await sweep()

    run(go())
    id_ = ids[0]
    (line,) = events(capsys.readouterr().out, "initiative.decided")
    assert line["speaks"] == "true" and line["score"] == "0.0"
    assert line["roll"] == str(round(roll(f"wake:{id_}"), 2))
    assert line["outcome"] == ("full" if roll(f"wake:{id_}") < 0.5 else "short")
    assert HERS not in str(line)


def test_a_checkpoint_keeps_the_moment_so_a_resumed_turn_decides_the_same() -> None:
    m = Moment("wake:3", 19, 1, 5000.0, None, 120.5)
    made = checkpoint()
    kept = replace(made, inbound=replace(made.inbound, moment=m))
    assert loads(dumps(kept)).inbound.moment == m
    assert loads(dumps(made)).inbound.moment is None
