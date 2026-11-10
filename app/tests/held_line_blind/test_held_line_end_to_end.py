"""A held line on web chat, end to end over Postgres: `respond` with `later=True` returns her line at once marked
`follows`, and it is already stored as her turn; the answer is stored later as a separate turn, not `follows`. A
resumed turn (another runner) never stores the held line again."""

import asyncio
from collections.abc import Callable

import psycopg
from ashley import services
from ashley.channels import resume
from ashley.conversations.inflight import Claim, InFlight, Orphan
from ashley.conversations.model import AgreedOutcome, NewTurn, Turn
from ashley.channels.respond import respond
from contract.conversations_support import run, scalar
from hl_support import CHECKING, DONE, HANG, World, database, settled, switch_on


class LosesTheClaim(InFlight):
    """The real store, but each claim it begins runs out at once and another runner takes the work."""

    def __init__(self, real: InFlight, url: str) -> None:
        self.real = real
        self.url = url

    @property
    def claim_s(self) -> float:
        return self.real.claim_s

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        claim = await self.real.begin(conversation_id, said_id, checkpoint)
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(b"UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")
        assert len(await self.real.orphaned(5)) == 1
        return claim

    async def save(self, claim: Claim, checkpoint: str) -> None:
        await self.real.save(claim, checkpoint)

    async def renew(self, claim: Claim) -> None:
        await self.real.renew(claim)

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        return await self.real.said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        return await self.real.finish(claim, turn, after)

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        await self.real.agreed(claim, outcome)

    async def drop(self, claim: Claim) -> bool:
        return await self.real.drop(claim)

    async def orphaned(self, limit: int) -> list[Orphan]:
        return await self.real.orphaned(limit)

    async def working(self, conversation_id: int) -> frozenset[int]:
        return await self.real.working(conversation_id)


def _file_of(task: "asyncio.Task[object]") -> str:
    code = getattr(task.get_coro(), "cr_code", None)
    return str(getattr(code, "co_filename", ""))


def _kill_the_turn() -> int:
    """Cancel every task running the app's own turn code (the continuation and its heartbeat), as a dead pod does;
    the database's pool is left alone."""
    mine = [t for t in asyncio.all_tasks() if "/ashley/channels/" in _file_of(t)]
    for task in mine:
        task.cancel()
    return len(mine)


def test_the_held_line_is_stored_as_hers_marked_follows_before_respond_returns(world: World) -> None:
    world.first.model.script = [CHECKING, DONE]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert (out.follows, out.body) == (True, CHECKING.text)
            assert world.turns()[:2] == [("person", "turn on the lamp", False), ("ashley", CHECKING.text, True)]
            await settled(world, 2)

    run(go())


def test_the_answer_is_a_separate_later_turn_that_does_not_follow(world: World) -> None:
    world.first.model.script = [CHECKING, DONE]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await settled(world, 2)
            await asyncio.sleep(0.2)

    run(go())
    assert world.turns() == [("person", "turn on the lamp", False), ("ashley", CHECKING.text, True),
                             ("ashley", DONE.text, False)]
    assert world.work() == 0


def test_the_tool_loop_runs_on_after_the_held_line_and_the_line_is_stored_once(world: World) -> None:
    world.first.model.script = [CHECKING, switch_on(), DONE]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert out.follows
            await settled(world, 2)

    run(go())
    assert world.hers() == [(CHECKING.text, True), (DONE.text, False)]
    assert len(world.first.tools.ran) == 1


def test_a_reply_that_is_the_answer_is_not_marked_follows(world: World) -> None:
    world.first.model.script = [DONE]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert not out.follows
            await asyncio.sleep(0.2)

    run(go())
    assert world.hers() == [(DONE.text, False)]


def test_a_persons_turn_is_never_marked_follows(world: World) -> None:
    world.first.model.script = [CHECKING, DONE]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound("one"))
            await settled(world, 2)
            world.first.model.script = [DONE]
            await respond(world.inbound("two"))
            await settled(world, 3)

    run(go())
    assert [f for a, _, f in world.turns() if a == "person"] == [False, False]


def test_a_resumed_turn_does_not_store_the_held_line_again(world: World) -> None:
    world.first.model.script = [CHECKING, switch_on(), HANG]
    world.second.model.script = [DONE]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert out.follows
            await asyncio.wait_for(world.first.model.asked.wait(), 5)
            killed = _kill_the_turn()
            assert killed >= 1
            await asyncio.sleep(0.45)
            world.as_pod(world.second)
            assert await resume.sweep() == 1
            assert await resume.sweep() == 0

    run(go())
    assert world.hers() == [(CHECKING.text, True), (DONE.text, False)]
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []


def test_a_runner_that_lost_the_turn_does_not_add_a_held_line(world: World) -> None:
    """The claim runs out and another runner takes the work before the line is said: nothing of this runner's is
    stored."""
    world.first.model.script = [CHECKING, DONE]

    async def go() -> None:
        async with database(world):
            services.register(InFlight, LosesTheClaim(services.get(InFlight), world.url))
            world.as_pod(world.first)
            try:
                await asyncio.wait_for(respond(world.inbound()), 5)
            except Exception:
                pass
            await asyncio.sleep(0.3)

    run(go())
    assert [t for t in world.hers()] == []
    assert scalar(world.url, "SELECT count(*) FROM turns WHERE author = 'ashley'") == 0
