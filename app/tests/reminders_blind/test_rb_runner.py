"""`runner.sweep()` on reminders over the real turn loop: a due reminder is one turn of hers on the person's push thread,
delivered to them alone, whatever Initiative says, with only tools that read; racing runners and kills give one push; a missed
occurrence fires once, late, and the series carries on in the future."""

import asyncio
from typing import Any
from datetime import timedelta

import psycopg
import pytest
from ashley.channels.wake import runner
from ashley.channels.wake.config import CONFIG as WAKES
from ashley.initiative.initiative import NullInitiative
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.reply import Reply
from contract.conversations_support import person, scalar
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, HANG, World
from repeat_support import next_of as next_after
from rb_support import DONE, PLANTED, SECOND, ZONE, monthly_first, now, stack

QUIET_REPLY = Reply(spoken="Nothing.", text="Nothing.", worth_saying=False)


def seen(prompt: object) -> str:
    return repr(getattr(prompt, "messages")) + repr(getattr(prompt, "system"))


def test_a_due_reminder_is_one_turn_pushed_to_its_person_alone_and_settled(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            assert await runner.sweep() == 1
            assert (await s.pushes()) == [f"push:{s.alana}"]
            assert s.hers() == [DONE.text]
            assert s.unsettled() == 0
            assert await runner.sweep() == 0
            assert (await s.pushes()) == [f"push:{s.alana}"]

    run(go())
    (prompt,) = world.first.inference.prompts
    assert "PLANTED-VISA-zq" in seen(prompt)


def test_a_reminder_not_yet_due_does_not_fire(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(due_in_s=3600.0)
            assert await runner.sweep() == 0
            assert (await s.pushes()) == [] and world.first.inference.prompts == []

    run(go())


def test_a_reminder_for_sam_set_by_alana_goes_to_sam_alone(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(who=s.sam.id, by=s.alana)
            await runner.sweep()
            assert (await s.pushes()) == [f"push:{s.sam.id}"]

    run(go())


def test_it_goes_out_when_initiative_would_keep_quiet(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world, NullInitiative()) as s:
            await s.schedule()
            await runner.sweep()
            assert (await s.pushes()) == [f"push:{s.alana}"]
            assert s.hers() == [DONE.text]

    run(go())


def test_it_goes_out_when_her_reply_says_it_is_not_worth_saying(world: World) -> None:
    world.first.inference.script = [QUIET_REPLY]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            await runner.sweep()
            assert (await s.pushes()) == [f"push:{s.alana}"]
            assert s.hers() == [QUIET_REPLY.text]

    run(go())


def test_the_turn_offers_only_tools_that_read(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            await runner.sweep()

    run(go())
    (prompt,) = world.first.inference.prompts
    assert all(t.reads for t in prompt.tools)
    assert world.first.tools.ran == []


def test_a_once_reminder_leaves_no_successor(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            await runner.sweep()
            assert [x.state for x in await s.wakes.reminders(s.house, s.alana)] == ["sending"]
            await s.deliver()
            assert await s.wakes.reminders(s.house, s.alana) == ()
            assert await s.wakes.due(10) == ()

    run(go())


def test_a_repeating_reminder_fires_and_the_next_occurrence_is_the_next_one_in_the_future(world: World) -> None:
    world.first.inference.script = [DONE]
    repeat = monthly_first(1)

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(repeat=repeat, due_at=next_after(repeat, now() - timedelta(days=100), ZONE))
            before = now()
            await runner.sweep()
            await s.deliver()
            (nxt,) = await s.wakes.reminders(s.house, s.alana)
            assert nxt.reminder.due_at == next_after(repeat, before, ZONE) and nxt.reminder.due_at > now()
            assert nxt.reminder.repeat == repeat and nxt.reminder.brief == PLANTED
            assert (nxt.reminder.person_id, nxt.reminder.made_by) == (s.alana, s.alana)
            assert await runner.sweep() == 0
            assert len((await s.pushes())) == 1

    run(go())


def test_an_outage_spanning_two_due_times_fires_once_late_then_schedules_the_next_future_one(world: World) -> None:
    world.first.inference.script = [DONE, SECOND]
    repeat = monthly_first(3)

    async def go() -> None:
        async with stack(world) as s:
            first = next_after(repeat, now() - timedelta(days=150), ZONE)
            assert next_after(repeat, first, ZONE) < now()
            await s.schedule(repeat=repeat, due_at=first)
            before = now()
            await runner.sweep()
            await runner.sweep()
            assert len((await s.pushes())) == 1 and s.hers() == [DONE.text]
            (nxt,) = await s.wakes.reminders(s.house, s.alana)
            assert nxt.reminder.due_at > now()
            assert nxt.reminder.due_at == next_after(repeat, before, ZONE)

    run(go())


def test_two_runners_at_once_give_one_push_and_one_successor(world: World) -> None:
    world.first.inference.script = [DONE, SECOND]
    repeat = monthly_first(1)

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(repeat=repeat, due_at=next_after(repeat, now() - timedelta(days=50), ZONE))
            await asyncio.gather(runner.sweep(), runner.sweep())
            await runner.sweep()
            assert len((await s.pushes())) == 1 and len(s.hers()) == 1
            assert len(await s.wakes.reminders(s.house, s.alana)) == 1
            assert s.unsettled() == 1

    run(go())


def test_a_runner_killed_between_its_answer_and_settling_gives_one_push_in_all(world: World) -> None:
    world.first.inference.script = [DONE]
    world.second.inference.script = [SECOND]
    repeat = monthly_first(1)

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(repeat=repeat, due_at=next_after(repeat, now() - timedelta(days=50), ZONE))
            s.wakes.hang = True
            world.as_pod(world.first)
            task = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(s.wakes.at_settle.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert s.hers() == [DONE.text] and await s.pushes() == []
            s.wakes.hang = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            await runner.sweep()
            await runner.sweep()
            assert len((await s.pushes())) == 1 and s.hers() == [DONE.text]
            assert len(await s.wakes.reminders(s.house, s.alana)) == 1
            assert s.unsettled() == 1

    run(go())


def test_a_runner_killed_mid_answer_leaves_the_reminder_due_and_the_next_sweep_pushes_it_once(world: World) -> None:
    world.first.inference.script = [HANG]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            world.as_pod(world.first)
            task = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(world.first.inference.asked.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (await s.pushes()) == [] and s.unsettled() == 1
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            from ashley.channels import resume

            await runner.sweep()
            await resume.sweep()
            await runner.sweep()
            assert (await s.pushes()) == [f"push:{s.alana}"] and s.hers() == [DONE.text]
            assert s.unsettled() == 0

    run(go())


def test_a_reminder_never_expires(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(due_in_s=-86400.0 * 400)
            await runner.sweep()
            assert (await s.pushes()) == [f"push:{s.alana}"]

    run(go())


def test_a_cancelled_reminder_never_fires(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.schedule()
            assert await s.wakes.cancel(s.house, s.alana, id_) is True
            assert await runner.sweep() == 0
            assert (await s.pushes()) == [] and world.first.inference.prompts == []

    run(go())


def test_nothing_the_reminder_says_reaches_a_log(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley import logs

    logs.setup({"LOG_LEVEL": "debug"})
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule(repeat=monthly_first(1), due_at=now() - timedelta(seconds=5))
            await runner.sweep()
            await runner.sweep()

    run(go())
    out = capsys.readouterr()
    text = out.out + out.err
    assert text and "PLANTED" not in text and "500 dollars" not in text and "Visa" not in text


def test_a_model_that_is_unavailable_leaves_the_reminder_due_and_it_is_pushed_once_later(world: World) -> None:
    async def unavailable(*a: object, **k: object) -> object:
        raise InferenceUnavailable("down")

    first: Any = world.first.inference
    first.step = unavailable
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            await runner.sweep()
            assert s.unsettled() == 1 and (await s.pushes()) == []
            world.as_pod(world.second)
            await runner.sweep()
            await runner.sweep()
            assert (await s.pushes()) == [f"push:{s.alana}"] and s.unsettled() == 0

    run(go())


def test_a_model_that_refuses_ends_that_occurrence_but_not_a_repeating_series(world: World) -> None:
    async def refused(*a: object, **k: object) -> object:
        raise InferenceRefused("no")

    first: Any = world.first.inference
    first.step = refused
    repeat = monthly_first(1)

    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.schedule(repeat=repeat, due_at=next_after(repeat, now() - timedelta(days=50), ZONE))
            for _ in range(WAKES.fire_attempts):
                assert scalar(world.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) is None
                await runner.sweep()
                make_due(world.url)
            assert (await s.pushes()) == []
            assert scalar(world.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) == "failed"
            listed = await s.wakes.reminders(s.house, s.alana)
            assert [(x.id, x.state) for x in listed if x.id == id_] == [(id_, "failed")]
            (nxt,) = [x for x in listed if x.id != id_]
            assert nxt.reminder.due_at > now() and nxt.state == "scheduled"
            assert await runner.sweep() == 0

    run(go())


def test_a_reminder_for_someone_no_longer_of_the_household_pushes_nothing_and_is_refired_then_settled_no_person(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            gone = person(world.url, s.house, "Gone")
            await s.schedule(who=gone)
            await s.schedule(by=gone)
            left: list[int] = []
            for _ in range(WAKES.fire_attempts):
                await runner.sweep()
                left.append(s.unsettled())
                make_due(world.url)
            assert left == [2, 2, 0]
            assert (await s.pushes()) == [] and world.first.inference.prompts == []
            assert scalar(world.url, "SELECT count(*) FROM wakes WHERE outcome = 'no_person'") == 2

    run(go())


def test_settled_reminders_are_pruned_after_a_week_and_one_still_to_fire_never_is(world: World) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.schedule()
            future = await s.schedule(due_in_s=86400.0 * 400)
            await runner.sweep()
            await s.deliver()
            assert _rows(world.url) == 2
            _age_settled(world.url, 86400.0 * 8)
            await runner.sweep()
            assert _rows(world.url) == 1
            assert [r.id for r in await s.wakes.reminders(s.house, s.alana)] == [future]

    run(go())


def make_due(url: str) -> None:
    """Every wake that was fired and could not run falls due now, as its refire delay passing would make it."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE wakes SET due_at = now() - interval '1 second' WHERE outcome IS NULL AND fire_attempts > 0")


def _rows(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM wakes"))


def _age_settled(url: str, seconds: float) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE wakes SET settled_at = settled_at - make_interval(secs => %s) WHERE settled_at IS NOT NULL",
                     (seconds,))
