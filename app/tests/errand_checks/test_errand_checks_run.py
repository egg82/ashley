"""An errand carried out over time, through the `wakes` runner and the real turn loop: each check is one turn that may
set the next with its plan, the next check sees that plan, a check that sets none ends it, a next check past its end
is refused, a check killed on one pod is finished on another that still sets the next, and the checks run only on the
pod holding the lease, the next one taken up by whichever pod holds it then."""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import uuid4

import pytest
from ashley import services
from ashley.channels import resume
from ashley.channels.wake import runner
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.referee.postgres_lease import PostgresLease
from ashley.senses.wakes import Reminder
from contract.conversations_support import run, scalar
from contract.lease_support import wait_until
from contract.test_inflight_resume import CLAIM_S, HANG, ScriptedInference, World
from rb_support import now, stack

ASK = "PLANTED-ERRAND-kq help me get up by seven"
QUIET = Reply(spoken="Nothing yet.", text="Nothing yet.", says="none")
DONE = Reply(spoken="You are up; I stopped.", text="You are up; I stopped.")
HOLDER: ContextVar[str] = ContextVar("holder", default="none")


def check_again(minutes: int, plan: str) -> ToolCalls:
    return ToolCalls((ToolCall("c1", "check_again", {"minutes": minutes, "plan": plan}),))


def errand(house: int, who: int, hours: float = 2.0) -> Reminder:
    due = now() - timedelta(seconds=1)
    return Reminder(house, who, who, ASK, due, None, ends_at=due + timedelta(hours=hours))


def seen(prompt: object) -> str:
    return repr(getattr(prompt, "messages")) + repr(getattr(prompt, "system"))


def next_checks(url: str) -> list[tuple[str, ...]]:
    got = scalar(url, "SELECT coalesce(string_agg(id || ':' || follows || ':' || plan, '|' ORDER BY id), '') "
                      "FROM wakes WHERE follows IS NOT NULL")
    return [tuple(row.split(":", 2)) for row in str(got).split("|") if row]


def bring_due(url: str) -> None:
    scalar(url, "WITH u AS (UPDATE wakes SET due_at = now() - interval '1 second' WHERE settled_at IS NULL "
                "RETURNING 1) SELECT count(*) FROM u")


def test_a_check_sets_the_next_with_its_plan_the_next_sees_it_and_one_that_sets_none_ends_the_errand(
        world: World) -> None:
    world.first.inference.script = [check_again(10, "PLAN-ONE lights at 6:50, still in bed"), QUIET, DONE]

    async def go() -> None:
        async with stack(world) as s:
            first = await s.wakes.schedule(errand(s.house, s.alana))
            assert await runner.sweep() == 1
            ((_, follows, plan),) = next_checks(world.url)
            assert follows == str(first) and plan.startswith("PLAN-ONE")
            assert await runner.sweep() == 0   # the next check waits for its time
            assert await s.pushes() == []   # a check with nothing to tell says nothing
            bring_due(world.url)
            assert await runner.sweep() == 1
            assert len(next_checks(world.url)) == 1 and s.unsettled() == 0
            assert await s.pushes() == [f"push:{s.alana}"]

    run(go())
    one, _, two = world.first.inference.prompts
    assert ASK in seen(one) and "first check" in seen(one) and "check_again" in seen(one)
    assert ASK in seen(two) and "PLAN-ONE" in seen(two)


def test_a_next_check_past_the_errands_end_is_refused_and_the_errand_ends(world: World) -> None:
    world.first.inference.script = [check_again(30, "try again"), DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.wakes.schedule(errand(s.house, s.alana, hours=0.25))
            assert await runner.sweep() == 1
            assert next_checks(world.url) == [] and s.unsettled() == 0

    run(go())
    assert "ended" in seen(world.first.inference.prompts[1])


def test_a_check_killed_on_one_pod_is_finished_on_another_which_still_sets_the_next(world: World) -> None:
    world.first.inference.script = [HANG]
    world.second.inference.script = [check_again(10, "PLAN-RESUMED"), QUIET, DONE]

    async def go() -> None:
        async with stack(world) as s:
            first = await s.wakes.schedule(errand(s.house, s.alana))
            world.as_pod(world.first)
            task = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(world.first.inference.asked.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert next_checks(world.url) == [] and s.unsettled() == 1
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            await runner.sweep()   # hands the check in again: its work is the resumer's, and the check is settled
            await resume.sweep()   # the resumer finishes it from the checkpoint, and its next check is still stored
            ((_, follows, plan),) = next_checks(world.url)
            assert follows == str(first) and plan == "PLAN-RESUMED"
            bring_due(world.url)
            assert await runner.sweep() == 1
            assert s.unsettled() == 0 and len(next_checks(world.url)) == 1

    run(go())
    assert "PLAN-RESUMED" in seen(world.second.inference.prompts[-1])


@dataclass
class Tagged(ScriptedInference):
    """A scripted model that records which lease holder's runner asked each step."""

    by: list[str] = field(default_factory=list[str])

    async def step(self, task: Any, prompt: Any, output: type[Any], *, conversation_id: int | None = None) -> Any:
        self.by.append(HOLDER.get())
        return await super().step(task, prompt, output, conversation_id=conversation_id)


async def quick(seconds: float) -> None:
    await asyncio.sleep(0.02)


async def held_by(holder: str) -> None:
    HOLDER.set(holder)
    await runner.run(quick)


def test_checks_run_only_under_the_lease_and_the_next_is_taken_by_whichever_pod_holds_it_then(world: World) -> None:
    model = Tagged(script=[check_again(10, "PLAN-LEASED"), QUIET, DONE])
    name = f"wakes-{uuid4().hex}"

    async def go() -> None:
        async with stack(world) as s:
            services.register(Inference, model)
            await s.wakes.schedule(errand(s.house, s.alana))
            sites = {h: asyncio.create_task(PostgresLease(world.url, 0.05, h).run(name, partial(held_by, h)))
                     for h in ("a", "b")}
            await wait_until(lambda: len(next_checks(world.url)) == 1 and len(model.by) == 2 and s.unsettled() == 1)
            first = model.by[0]
            assert model.by == [first, first]
            sites[first].cancel()   # the site holding the lease is lost
            await asyncio.gather(sites[first], return_exceptions=True)
            bring_due(world.url)
            await wait_until(lambda: len(model.by) == 3 and s.unsettled() == 0)
            other = sites.pop("b" if first == "a" else "a")
            other.cancel()
            await asyncio.gather(other, return_exceptions=True)
            assert model.by[2] != first and next_checks(world.url)[0][2] == "PLAN-LEASED"

    run(go())
