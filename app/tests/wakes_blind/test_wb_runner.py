"""`runner.sweep()` end to end: a due wake with exactly one rule becomes one turn of her own with the rule's brief and
only its tools; the other outcomes settle without a turn; a quiet reply queues nothing; a kill and a second hand-in is
one turn; an unavailable model leaves the wake due, a refused one settles it failed; nothing of the wake reaches a log."""

import asyncio
import json
from typing import Any

import pytest
from ashley import logs
from ashley.channels import resume
from ashley.initiative.initiative import NullInitiative
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.channels.unprompted import QUIET
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, HANG, World
from wb_runner_support import (ALLOWED, DONE, FORBIDDEN, SILENT, call, results, seen_by_model, stack, sweep, ran)

HERS = DONE.text


def test_a_due_wake_with_one_rule_is_one_turn_of_hers_and_is_settled_turn(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            assert await sweep() == 1
            assert s.outcome(id_) == "turn" and s.turns_of(id_) == 1
            assert await sweep() == 0

    run(go())
    assert world.hers() == [HERS]


def test_her_turn_is_given_the_rules_brief(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.hand_in()
            await sweep()

    run(go())
    (prompt,) = world.first.inference.prompts
    assert "PLANTED-BRIEF-zq" in seen_by_model(prompt)


def test_only_the_rules_tools_are_offered_and_callable(world: World) -> None:
    world.first.inference.script = [call("lamp_on"), call("garage_open", "c2"), DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule(tools=("lamp_on",))
            await s.hand_in()
            await sweep()

    run(go())
    first, second, third = world.first.inference.prompts
    assert [t.name for t in first.tools] == [ALLOWED.name]
    assert [r.is_error for r in results(second)] == [False]
    assert [r.is_error for r in results(third)] == [False, True]
    assert [c.name for c in ran(world.first)] == [ALLOWED.name]


def test_a_rule_naming_no_tools_offers_none(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule(tools=())
            await s.hand_in()
            await sweep()

    run(go())
    assert world.first.inference.prompts[0].tools == ()


def test_a_rule_names_tools_the_way_excluding_matches_them(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule(tools=("garage_open",))
            await s.hand_in()
            await sweep()

    run(go())
    assert [t.name for t in world.first.inference.prompts[0].tools] == [FORBIDDEN.name]


@pytest.mark.parametrize("initiative_says", [True, False])
def test_what_goes_out_is_initiatives_to_say_and_a_quiet_reply_queues_nothing(world: World, initiative_says: bool) -> None:
    world.first.inference.script = [DONE if initiative_says else SILENT]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            await sweep()
            assert s.outcome(id_) == "turn"
            assert s.queued() == (1 if initiative_says else 0)

    run(go())
    if initiative_says:
        assert world.hers() == [HERS]
    else:
        assert world.hers() == [QUIET]


def test_with_no_initiative_wired_she_stays_quiet_whatever_the_reply_says(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world, NullInitiative()) as s:
            await s.rule()
            await s.hand_in()
            await sweep()
            assert s.queued() == 0

    run(go())
    assert HERS not in " ".join(world.hers())


def test_a_wake_no_rule_answers_is_settled_no_rule_without_a_turn(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await s.rule(event="left")
            id_ = await s.hand_in(event="arrived")
            await sweep()
            assert s.outcome(id_) == "no_rule" and s.turns_of(id_) == 0

    run(go())
    assert world.first.inference.prompts == [] and world.hers() == []


def test_two_rules_for_one_event_are_ambiguous_and_neither_runs(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.rule(brief="Another way.")
            id_ = await s.hand_in()
            await sweep()
            assert s.outcome(id_) == "ambiguous"

    run(go())
    assert world.first.inference.prompts == []


@pytest.mark.parametrize("who, runs", [("person.alana", "PLANTED-WHO-zq"), ("person.kim", "PLANTED-BRIEF-zq")])
def test_a_rule_kept_for_the_wakes_person_runs_over_the_bare_rule(world: World, capsys: pytest.CaptureFixture[str],
                                                                  who: str, runs: str) -> None:
    logs.setup({"LOG_LEVEL": "info"})
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    kept = json.dumps({"event": "arrived", "brief": "Only them, PLANTED-WHO-zq.", "tools": [], "who": who})

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.rule(body=kept)
            id_ = await s.hand_in()
            await sweep()
            assert s.outcome(id_) == "turn"

    run(go())
    (prompt,) = world.first.inference.prompts
    assert runs in seen_by_model(prompt)
    out = capsys.readouterr().out
    assert "event=wakes.rule" in out and "outcome=one" in out and "person.alana" not in out


def test_a_wake_about_nobody_of_the_household_is_no_person(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            a = await s.hand_in("e1", who="person.stranger")
            b = await s.hand_in("e2", who=None)
            await sweep()
            assert (s.outcome(a), s.outcome(b)) == ("no_person", "no_person")

    run(go())
    assert world.first.inference.prompts == []


def test_a_wake_that_waited_too_long_is_expired_and_runs_no_turn(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            s.age(id_, 3600)
            await sweep()
            assert s.outcome(id_) == "expired"

    run(go())
    assert world.first.inference.prompts == []


def test_a_rule_on_a_closed_bench_does_not_answer(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            bench = await s.rule()
            await s.workshop.close(s.owner, bench)
            id_ = await s.hand_in()
            await sweep()
            assert s.outcome(id_) == "no_rule"

    run(go())


def test_a_draft_rule_with_an_empty_body_answers_nothing(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await s.rule(body="")
            id_ = await s.hand_in()
            await sweep()
            assert s.outcome(id_) == "no_rule"

    run(go())


def test_the_runner_takes_oldest_first_and_only_a_batch_a_sweep(world: World) -> None:
    world.first.inference.script = [DONE] * 8
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            ids = [await s.hand_in(f"e{n}") for n in range(7)]
            assert await sweep() == 5
            assert [s.outcome(i) for i in ids] == ["turn"] * 5 + [None, None]
            assert await sweep() == 2

    run(go())


def test_a_wake_handed_in_twice_is_one_wake_one_turn(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            a = await s.hand_in("same")
            b = await s.hand_in("same")
            assert a == b
            await sweep()
            await sweep()
            assert s.turns_of(a) == 1

    run(go())
    assert world.hers() == [HERS]


def test_a_runner_killed_mid_turn_leaves_the_wake_due_and_the_next_sweep_makes_it_the_same_turn(world: World) -> None:
    world.first.inference.script = [call("lamp_on"), HANG]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            world.as_pod(world.first)
            task = asyncio.create_task(sweep())
            await asyncio.wait_for(world.first.inference.asked.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert s.outcome(id_) is None and world.hers() == []
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            await sweep()
            await resume.sweep()
            assert s.outcome(id_) == "turn" and s.turns_of(id_) == 1
            await sweep()
            await resume.sweep()
            assert s.turns_of(id_) == 1

    run(go())
    assert world.hers() == [HERS]
    assert len(ran(world.first)) == 1 and ran(world.second) == []


def test_a_wake_whose_runner_is_alive_is_not_run_twice(world: World) -> None:
    world.first.inference.script = [HANG]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.hand_in()
            world.as_pod(world.first)
            task = asyncio.create_task(sweep())
            await asyncio.wait_for(world.first.inference.asked.wait(), 10)
            world.as_pod(world.second)
            await asyncio.wait_for(sweep(), 5)
            assert world.second.inference.prompts == []
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    run(go())


def test_a_model_that_is_unavailable_leaves_the_wake_due_and_it_runs_once_later(world: World) -> None:
    world.first.inference.script = []

    async def unavailable(*a: object, **k: object) -> object:
        raise InferenceUnavailable("down")

    first: Any = world.first.inference
    first.step = unavailable
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            world.as_pod(world.first)
            await sweep()
            assert s.outcome(id_) is None
            world.as_pod(world.second)
            await sweep()
            assert s.outcome(id_) == "turn" and s.turns_of(id_) == 1
            await sweep()
            assert s.turns_of(id_) == 1

    run(go())
    assert world.hers() == [HERS]


def test_a_model_that_refuses_settles_the_wake_failed_and_it_is_not_tried_again(world: World) -> None:
    async def refused(*a: object, **k: object) -> object:
        raise InferenceRefused("no")

    first: Any = world.first.inference
    first.step = refused
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            world.as_pod(world.first)
            await sweep()
            assert s.outcome(id_) == "failed"
            world.as_pod(world.second)
            assert await sweep() == 0
            assert world.second.inference.prompts == []

    run(go())
