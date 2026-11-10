"""A `wakes` row of kind `watch` is taken up like any wake by the wakes runner (`WatchWake` in `Due.wake`): one turn of
hers, settled `turn`; left due while the turn cannot run; expired at `wake_max_age_s` (a day, not a house wake's
minutes); a refusal settles it `failed`; and the turn's source is the wake id, so handing it in twice is one turn."""

from typing import Any

import pytest
from ashley import logs
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.senses.wakes import Wakes
from ashley import services
from ashley.senses.wakes import WatchWake
from contract.conversations_support import run
from contract.test_inflight_resume import World
from wb_runner_support import DONE, sweep
from watch_turn_blind_support import LABEL, rig, run_sql

DAY_S = 86_400


def test_a_changed_wake_is_one_turn_of_hers_and_is_settled_turn(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed())
            due = await services.get(Wakes).due(10)
            assert [d.id for d in due] == [wake] and isinstance(due[0].wake, WatchWake)
            assert await sweep() == 1
            assert r.outcome(wake) == "turn"
            assert await sweep() == 0

    run(go())
    assert world.hers() == [DONE.text]


def test_a_paused_wake_is_taken_up_the_same_way(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.paused(await r.armed())
            assert await sweep() == 1
            assert r.outcome(wake) == "turn"

    run(go())
    assert world.hers() == [DONE.text]


def test_the_turns_source_is_the_wake_id(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed())
            await sweep()
            assert [s for _, s in r.household_turns()] == [f"wake:{wake}"]

    run(go())


def test_a_wake_handed_in_again_after_a_kill_is_the_same_turn(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed())
            await sweep()
            run_sql(r.url, "UPDATE wakes SET settled_at = NULL, outcome = NULL WHERE id = %s", (wake,))
            await sweep()
            assert len(r.household_turns()) == 1

    run(go())


def test_a_wake_whose_turn_cannot_run_stays_due_and_runs_once_on_another_pod(world: World) -> None:
    async def unavailable(*a: object, **k: object) -> object:
        raise InferenceUnavailable("down")

    first: Any = world.first.inference
    first.step = unavailable
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed())
            world.as_pod(world.first)
            await sweep()
            assert r.outcome(wake) is None
            world.as_pod(world.second)
            await sweep()
            assert r.outcome(wake) == "turn"
            assert await sweep() == 0

    run(go())
    assert world.hers() == [DONE.text]


def test_a_finish_told_an_hour_late_is_still_told(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed())
            r.age(wake, 3600)
            await sweep()
            assert r.outcome(wake) == "turn"

    run(go())


@pytest.mark.parametrize("which", ["changed", "paused"])
def test_a_wake_past_its_day_expires_unspoken(world: World, which: str) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            watch = await r.armed()
            wake = await (r.woke(watch) if which == "changed" else r.paused(watch))
            r.age(wake, 3 * DAY_S)
            await sweep()
            assert r.outcome(wake) == "expired"
            assert r.household_turns() == []

    run(go())
    assert world.hers() == []


def test_a_model_that_refuses_settles_the_wake_failed_and_it_is_not_tried_again(world: World) -> None:
    async def refused(*a: object, **k: object) -> object:
        raise InferenceRefused("no")

    first: Any = world.first.inference
    first.step = refused
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed())
            world.as_pod(world.first)
            await sweep()
            assert r.outcome(wake) == "failed"
            world.as_pod(world.second)
            assert await sweep() == 0

    run(go())
    assert world.hers() == []


def test_a_wake_of_a_watch_that_ended_is_still_told(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            wake = await r.woke(await r.armed(), ends="until")
            await sweep()
            assert r.outcome(wake) == "turn"

    run(go())


def test_nothing_of_the_watch_reaches_a_log_line(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            await r.woke(await r.armed(target="PLANTED-TARGET-wtb"))
            await sweep()

    run(go())
    out = capsys.readouterr().out
    assert "event=wakes.settled" in out
    for planted in (LABEL, "PLANTED-TARGET-wtb", DONE.text):
        assert planted not in out
