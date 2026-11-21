"""What a standing errand's round finds while the person's own quiet hours hold is kept for her next reply to them, as
a held answer is (`errands.postgres.HOLD`): one `done` errand of theirs for the round's turn, whichever pod finishes
the round, told once. A round outside quiet hours is sent as it was, and a round with nothing to tell holds nothing."""

import asyncio
from dataclasses import replace

import psycopg
import pytest
from ashley.channels import resume
from ashley.channels.wake import runner
from ashley.db.pool import PoolDatabase
from ashley.errands.postgres import HOLD, PostgresErrands
from ashley.people.model import QuietHours
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import CLAIM_S, HANG, World
from rb_support import now, stack
from test_standing_errands_run import FOUND, QUIET, instructed as instructed, skills_unwired as skills_unwired, standing

AROUND_NOW = QuietHours((now().hour - 1) % 24, (now().hour + 2) % 24, "UTC")
OTHER_HOURS = QuietHours((now().hour + 3) % 24, (now().hour + 5) % 24, "UTC")


def kept(url: str) -> list[tuple[str, str, str]]:
    rows = scalar(url, "SELECT coalesce(json_agg(json_build_array(source, state, result) ORDER BY id), '[]') "
                       "FROM errands")
    return [(r[0], r[1], r[2]) for r in rows]


async def untold(url: str, who: int) -> list[str]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        return [d.result for d in await PostgresErrands(db).untold(who, 5)]
    finally:
        await db.close()


def quiet_for(world: World, hours: QuietHours) -> None:
    world.who = replace(world.who, quiet=hours)


def test_a_finding_in_quiet_hours_is_sent_nowhere_and_kept_for_her_next_reply_told_once(instructed: World) -> None:
    world = instructed
    quiet_for(world, AROUND_NOW)
    world.first.inference.script = [FOUND]

    async def go() -> None:
        async with stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            assert await runner.sweep() == 1
            assert await s.pushes() == []
            assert kept(world.url) == [("outbox", "done", FOUND.text)]
            assert await untold(world.url, s.alana) == [FOUND.text]
            db = PoolDatabase(world.url, connect_timeout_s=5.0)
            await db.open()
            try:
                errands = PostgresErrands(db)
                (held,) = await errands.untold(s.alana, 5)
                await errands.told([held.id])
            finally:
                await db.close()
            assert await untold(world.url, s.alana) == []

    run(go())


def test_a_round_with_nothing_to_tell_in_quiet_hours_keeps_nothing(instructed: World) -> None:
    world = instructed
    quiet_for(world, AROUND_NOW)
    world.first.inference.script = [QUIET]

    async def go() -> None:
        async with stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            assert await runner.sweep() == 1
            assert await s.pushes() == []

    run(go())
    assert kept(world.url) == []


def test_a_finding_outside_quiet_hours_is_sent_and_not_kept(instructed: World) -> None:
    world = instructed
    quiet_for(world, OTHER_HOURS)
    world.first.inference.script = [FOUND]

    async def go() -> None:
        async with stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            assert await runner.sweep() == 1
            assert await s.pushes() == [f"push:{s.alana}"]

    run(go())
    assert kept(world.url) == []


def test_a_round_killed_on_one_pod_and_finished_on_another_keeps_its_finding_once(instructed: World) -> None:
    world = instructed
    quiet_for(world, AROUND_NOW)
    world.first.inference.script = [HANG]
    world.second.inference.script = [FOUND]

    async def go() -> None:
        async with stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            world.as_pod(world.first)
            task = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(world.first.inference.asked.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            await runner.sweep()
            await resume.sweep()
            await resume.sweep()
            assert await s.pushes() == []

    run(go())
    assert kept(world.url) == [("outbox", "done", FOUND.text)]


def test_the_same_round_held_twice_is_one_errand(instructed: World) -> None:
    """Two sites finishing the one round's turn both name it; the errand's turn is unique."""
    world = instructed
    quiet_for(world, AROUND_NOW)
    world.first.inference.script = [FOUND]

    async def go() -> None:
        async with stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            await runner.sweep()
            said = int(scalar(world.url, "SELECT id FROM turns WHERE author = 'person' AND source IS NOT NULL"))
            with psycopg.connect(world.url, autocommit=True) as conn:
                conn.execute(HOLD, ("again", said))

    run(go())
    assert kept(world.url) == [("outbox", "done", FOUND.text)]
