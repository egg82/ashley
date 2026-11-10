"""`Outbox.answer(claim, turn, pushed, after)`: her turn stored and every message in `pushed` queued in one transaction.
Postgres is real."""

import asyncio

import pytest
from ashley import services
from ashley.channels.model import Outbound
from ashley.channels.outbox import Pushed
from ashley.conversations.inflight import ClaimLost, InFlight
from ashley.conversations.model import NewTurn, Turn
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, World
from ipb_support import rig


def test_every_message_pushed_is_queued_with_her_turn(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            pushed = [r.push(conv, "discord:5", "Done."), r.push(conv, "push:1", "Done, with a link.")]
            stored = await r.outbox.answer(claim, NewTurn("ashley", "Done.", answers=claim.said_id), pushed)
            assert stored.author == "ashley" and stored.answers == claim.said_id
            taken = await r.outbox.take("")
            assert sorted((t.thread, t.household_id, t.outbound.body) for t in taken) == [
                ("discord:5", world.who.household_id, "Done."),
                ("push:1", world.who.household_id, "Done, with a link.")]
            assert await r.outbox.take("") == []

    run(go())
    assert world.hers() == ["Done."]


def test_nothing_pushed_stores_her_turn_and_queues_nothing(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, _ = await r.began()
            await r.outbox.answer(claim, NewTurn("ashley", "Done.", answers=claim.said_id), [])
            assert await r.outbox.take("") == []

    run(go())
    assert world.hers() == ["Done."]


def test_a_failure_inside_the_transaction_leaves_neither_the_turn_nor_any_message(world: World) -> None:
    def broken(stored: Turn) -> str:
        raise RuntimeError("no")

    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            pushed = [r.push(conv, "discord:5", "a"), r.push(conv, "push:1", "b")]
            with pytest.raises(RuntimeError):
                await r.outbox.answer(claim, NewTurn("ashley", "Done.", answers=claim.said_id), pushed, broken)
            assert await r.outbox.take("") == [] and await r.hers() == 0
            assert await services.get(InFlight).working(conv) == frozenset({claim.said_id})

    run(go())


def test_a_message_the_outbox_refuses_undoes_her_turn(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            good = r.push(conv, "discord:5", "a")
            refused = Pushed(987654, "push:1", Outbound(conv, "text", "b"))   # no such household
            with pytest.raises(Exception):
                await r.outbox.answer(claim, NewTurn("ashley", "Done.", answers=claim.said_id), [good, refused])
            assert await r.outbox.take("") == [] and await r.hers() == 0
            assert await services.get(InFlight).working(conv) == frozenset({claim.said_id})

    run(go())


def test_a_runner_killed_before_commit_leaves_neither_and_the_resume_leaves_each_once(world: World) -> None:
    def killed_here(stored: Turn) -> str:
        """Runs inside the transaction once the turn and the messages are written: cancels its own task, which the
        next await (the rest of the transaction) raises."""
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        return "act"

    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            pushed = [r.push(conv, "discord:5", "a"), r.push(conv, "push:1", "b")]
            runner = asyncio.create_task(r.outbox.answer(
                claim, NewTurn("ashley", "Done.", answers=claim.said_id), pushed, killed_here))
            with pytest.raises(asyncio.CancelledError):
                await runner
            assert await r.outbox.take("") == [] and await r.hers() == 0
            await asyncio.sleep(CLAIM_S * 1.5)
            (orphan,) = await services.get(InFlight).orphaned(10)
            await r.outbox.answer(orphan.claim, NewTurn("ashley", "Done.", answers=claim.said_id), pushed)
            assert sorted(t.outbound.body for t in await r.outbox.take("")) == ["a", "b"]
            assert await r.hers() == 1

    run(go())


def test_a_runner_that_lost_the_work_queues_and_stores_nothing(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            old, conv = await r.began()
            await asyncio.sleep(CLAIM_S * 1.5)
            (orphan,) = await services.get(InFlight).orphaned(10)
            with pytest.raises(ClaimLost):
                await r.outbox.answer(old, NewTurn("ashley", "late", answers=old.said_id),
                                      [r.push(conv, "push:1", "late")])
            assert await r.outbox.take("") == [] and await r.hers() == 0
            await r.outbox.answer(orphan.claim, NewTurn("ashley", "Done.", answers=old.said_id),
                                  [r.push(conv, "push:1", "Done.")])
            assert [t.outbound.body for t in await r.outbox.take("")] == ["Done."]

    run(go())


def test_a_turn_answered_by_one_runner_is_not_answered_and_queued_by_another(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            old, conv = await r.began()
            await asyncio.sleep(CLAIM_S * 1.5)
            (orphan,) = await services.get(InFlight).orphaned(10)
            await r.outbox.answer(orphan.claim, NewTurn("ashley", "once", answers=old.said_id),
                                  [r.push(conv, "push:1", "once")])
            with pytest.raises(ClaimLost):
                await r.outbox.answer(old, NewTurn("ashley", "twice", answers=old.said_id),
                                      [r.push(conv, "push:1", "twice")])
            assert [t.outbound.body for t in await r.outbox.take("")] == ["once"]
            assert await r.hers() == 1

    run(go())
