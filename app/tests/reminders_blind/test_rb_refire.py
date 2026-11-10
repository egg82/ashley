"""A firing that could not run (refused, or nobody to give it to) is refired after `retry_s`, up to `fire_attempts`
times, then settled and still listed until dismissed; a repeating reminder carries on with its next occurrence."""

from dataclasses import replace
from typing import Any
from datetime import timedelta

import psycopg
import pytest
from ashley.channels.push import reminders as push_reminders
from ashley.channels.wake import runner
from ashley.channels.wake.config import CONFIG as WAKES
from ashley.inference.inference import InferenceRefused
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import World
from rb_support import DONE, monthly_first, now, stack
from rb_delivery_support import listed, states

@pytest.fixture(autouse=True)
def quick_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry delay scaled from 300 s to a fifth of a second; the window stays a day."""
    monkeypatch.setattr(push_reminders, "WAKES", replace(WAKES, retry_s=0.2))



def refusing(world: World) -> list[int]:
    calls: list[int] = []

    async def refused(*a: object, **k: object) -> object:
        calls.append(1)
        raise InferenceRefused("no")

    first: Any = world.first.inference
    first.step = refused
    return calls


def make_due(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE wakes SET due_at = now() - interval '1 second' WHERE outcome IS NULL AND fire_attempts > 0")


def test_a_refused_firing_is_not_tried_again_until_the_delay_has_passed(world: World) -> None:
    calls = refusing(world)

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            await runner.sweep()
            assert len(calls) == 1 and s.unsettled() == 1
            assert await runner.sweep() == 0 and len(calls) == 1
            assert await states(s) == ["scheduled"]

    run(go())


def test_a_refused_firing_is_tried_three_times_in_all_then_failed_and_listed_failed(world: World) -> None:
    calls = refusing(world)

    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.schedule()
            for _ in range(5):
                await runner.sweep()
                make_due(world.url)
            assert len(calls) == WAKES.fire_attempts == 3
            assert scalar(world.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) == "failed"
            assert [(x.id, x.state) for x in await listed(s)] == [(id_, "failed")]
            assert await s.pushes() == [] and s.hers() == []

    run(go())


def test_a_failed_reminder_is_never_pruned_until_dismissed(world: World) -> None:
    refusing(world)

    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.schedule()
            for _ in range(4):
                await runner.sweep()
                make_due(world.url)
            with psycopg.connect(world.url, autocommit=True) as conn:
                conn.execute("UPDATE wakes SET settled_at = settled_at - interval '30 days' WHERE settled_at IS NOT NULL")
            await runner.sweep()
            assert [x.id for x in await listed(s)] == [id_]
            assert await s.wakes.dismiss(s.house, s.alana, id_) is True
            await runner.sweep()
            assert scalar(world.url, "SELECT count(*) FROM wakes") == 0

    run(go())


def test_a_firing_refused_once_and_then_accepted_is_one_turn_one_push(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            first: Any = world.first.inference
            real = first.step
            seen: list[int] = []

            async def once(*a: object, **k: object) -> object:
                seen.append(1)
                if len(seen) == 1:
                    raise InferenceRefused("no")
                return await real(*a, **k)

            first.step = once
            first.script = [DONE]
            id_ = await s.schedule()
            await runner.sweep()
            make_due(world.url)
            await runner.sweep()
            await runner.sweep()
            assert scalar(world.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) == "turn"
            assert await s.pushes() == [f"push:{s.alana}"] and s.hers() == [DONE.text]

    run(go())


def test_a_repeating_reminder_whose_firing_failed_carries_on_with_its_next_occurrence(world: World) -> None:
    refusing(world)
    repeat = monthly_first(1)

    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.schedule(repeat=repeat, due_at=now() - timedelta(seconds=5))
            for _ in range(4):
                await runner.sweep()
                make_due(world.url)
            got = {x.id: x.state for x in await listed(s)}
            assert got[id_] == "failed" and sorted(got.values()) == ["failed", "scheduled"]

    run(go())
