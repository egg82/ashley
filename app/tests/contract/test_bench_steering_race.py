"""Every message on a bench is answered exactly once, whatever the interleaving with the running turn (`decisions.md`,
"A message on a bench steers the running turn"). Each test forces one interleaving by hooking the running turn at the
exact point, and sends the second message as another pod does: through its own database pool. Postgres is real; the
model and tools are fakes."""

import asyncio
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager
from typing import Any

import pytest
from ashley import services
from ashley.channels import steering
from ashley.channels.model import Inbound, Outbound
from ashley.channels.respond import RespondRefused, respond
from ashley.conversations import postgres_queries
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import InferenceRefused
from ashley.inference.model import Message
from contract.conversations_support import POLICY, run, scalar
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.test_bench_steering import ANOTHER, SAID, SECOND, Hooked, Sends, bench_turn
from contract.test_inflight_resume import CLAIM_S, DONE, Pod, World, database, switch_on
from contract.test_inflight_resume import sweep
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world


@asynccontextmanager
async def other_pod(world: World) -> AsyncGenerator[None]:
    """Conversations and InFlight through a pool of their own, as another pod reaches the database, for the block."""
    mine = services.get(Conversations), services.get(InFlight)
    db = PoolDatabase(world.url, connect_timeout_s=5.0)
    await db.open()
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, claim_s=CLAIM_S))
    try:
        yield
    finally:
        services.register(Conversations, mine[0])
        services.register(InFlight, mine[1])
        await db.close()


async def sent_from_other_pod(world: World, seen: list[Outbound]) -> None:
    async with other_pod(world):
        seen.append(await respond(bench_turn(world, SECOND)))


def after_final_hand(world: World, monkeypatch: pytest.MonkeyPatch, seen: list[Outbound]) -> None:
    """The second message is stored on another pod right after the running turn's hand that found nothing following
    her first reply, before her answer is stored: the window between the last hand and the final store."""
    real = steering.hand
    sent: list[bool] = []

    async def hooked(inbound: Inbound, conversation_id: int, said_id: int,
                     handed: Collection[int]) -> list[tuple[int, Message]]:
        got = await real(inbound, conversation_id, said_id, handed)
        if not got and not sent and len(world.first.inference.prompts) == 1:
            sent.append(True)
            await sent_from_other_pod(world, seen)
        return got

    monkeypatch.setattr(steering, "hand", hooked)


def test_a_message_stored_after_the_last_hand_and_before_her_answer_is_handed_to_the_turn_once(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.first.inference.script = [DONE, ANOTHER]
    seen: list[Outbound] = []
    after_final_hand(world, monkeypatch, seen)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            assert (await respond(bench_turn(world))).body == ANOTHER.text

    run(go())
    assert [(o.follows, o.body) for o in seen] == [(True, "")]
    last = [e.text for e in world.first.inference.prompts[1].messages if isinstance(e, Message)]
    assert last[-2:] == [DONE.text, SAID]
    assert world.hers() == [ANOTHER.text]
    assert scalar(world.url, "SELECT count(*) FROM turn_work") == 0


async def lock_waiter(url: str) -> None:
    """Until some session waits on a row lock: the second pod's store of the message, behind her answer's."""
    for _ in range(500):
        waiting = scalar(url, "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the message's store never waited on her answer's lock")


def test_a_message_stored_while_her_answer_is_being_stored_waits_for_it_and_gets_its_own_turn(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.first.inference.script = [DONE, ANOTHER]
    seen: list[Outbound] = []
    real = postgres_queries.all_handed
    pending: list[asyncio.Task[None]] = []

    async def hooked(conn: Any, conversation_id: int, turn: NewTurn) -> None:
        if turn.handed is not None and not pending:
            pending.append(asyncio.create_task(sent_from_other_pod(world, seen)))
            await lock_waiter(world.url)
        await real(conn, conversation_id, turn)

    monkeypatch.setattr(postgres_queries, "all_handed", hooked)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            assert (await respond(bench_turn(world))).body == DONE.text
            await asyncio.wait_for(pending[0], 5)

    run(go())
    assert [(o.follows, o.body) for o in seen] == [(False, ANOTHER.text)]
    assert world.hers() == [DONE.text, ANOTHER.text]



def test_a_message_left_to_a_turn_that_fails_gets_one_turn_of_its_own_from_any_pod(world: World) -> None:
    tools = Sends()
    pod = Pod(Hooked(), tools)
    world.first = pod
    pod.inference.script = [switch_on()]
    world.second.inference.script = [ANOTHER]
    seen: list[Outbound] = []

    async def refused() -> None:
        raise InferenceRefused("no")

    async def second() -> None:
        seen.append(await respond(bench_turn(world, SECOND)))

    assert isinstance(pod.inference, Hooked)
    pod.inference.before = {1: refused}
    tools.during = second

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            with pytest.raises(RespondRefused):
                await respond(bench_turn(world))
            world.as_pod(world.second)
            assert await sweep() == 1
            assert await sweep() == 0

    run(go())
    assert [(o.follows, o.body) for o in seen] == [(True, "")]
    asked = [e.text for e in world.second.inference.prompts[0].messages if isinstance(e, Message)]
    assert asked[-1] == f"Alana: {SECOND}"
    assert world.hers() == [ANOTHER.text]
    assert scalar(world.url, "SELECT answers FROM turns WHERE author = 'ashley'") == scalar(
        world.url, "SELECT id FROM turns WHERE text = %s", (SECOND,))
    assert scalar(world.url, "SELECT count(*) FROM turn_work") == 0
