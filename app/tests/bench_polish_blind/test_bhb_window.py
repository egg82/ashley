"""The window just before her final store: a message stored after the turn's last hand refuses her answer
(`Unhanded`), the turn takes it after her draft and goes on, and every message is answered exactly once, whichever of
two pods' stores reaches the conversation's lock first."""

import asyncio

import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations, Unhanded
from ashley.conversations.model import NewTurn
from ashley.inference.model import Message
from bhb_support import World, pods, reply, said
from contract.conversations_support import run, scalar
from psycopg import AsyncConnection

LOCK = "SELECT 1 FROM conversations WHERE id = %s FOR UPDATE"


async def lock_waiters(url: str, count: int, timeout: float = 5.0) -> None:
    """Wait, on the database's own view, until `count` backends wait on a lock."""
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        async with asyncio.timeout(timeout):
            while True:
                cur = await conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                         "AND wait_event_type = 'Lock'")
                row = await cur.fetchone()
                assert row is not None
                if row[0] == count:
                    return
                await asyncio.sleep(0.01)


def test_a_message_stored_between_the_last_hand_and_the_final_store_is_taken_by_the_turn(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            seen: list[object] = []

            async def other_pod_message() -> None:
                seen.append(await world.from_pod(2, world.bench_say("one more thing")))

            world.inflight[1].before_finish = other_pod_message
            world.model.play(reply("draft answer"), reply("answer covering both"))
            out = await respond(world.bench_say("question"))
            assert getattr(seen[0], "follows") is True and getattr(seen[0], "body") == ""
            assert out.body == "answer covering both"
            assert world.model.steps == 2
            second = world.model.prompts[1].messages
            assert said(world.model.prompts[1]) == ["Alana just said: one more thing"]
            assert isinstance(second[-1], Message) and second[-1].text == "Alana just said: one more thing"
            assert any(isinstance(e, Message) and e.author == "ashley" and e.text == "draft answer" for e in second)
            assert [(a, t) for a, t, _ in world.talk()] == [("person", "question"), ("person", "one more thing"),
                                                            ("ashley", "answer covering both")]
            assert world.work() == 0

    run(go())


def test_her_final_store_refuses_an_answer_not_handed_every_message_after_the_one_it_answers(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            await respond(world.bench_say("seed"))
            cid = world.thread_conversation(f"bench:{world.bench.id}")
            seed = int(scalar(world.url, "SELECT id FROM turns WHERE conversation_id = %s AND author = 'person'",
                              (cid,)))
            conversations = services.get(Conversations)
            asked = await conversations.add_turn(cid, NewTurn("person", "unanswered", world.who.id, "private"))
            before = world.talk()
            with pytest.raises(Unhanded):
                await conversations.add_turn(cid, NewTurn("ashley", "refused", None, "private", answers=seed,
                                                          handed=()))
            assert world.talk() == before, "an answer refused as Unhanded wrote nothing"
            stored = await conversations.add_turn(cid, NewTurn("ashley", "accepted", None, "private", answers=seed,
                                                               handed=(asked.id,)))
            assert stored.text == "accepted"

    world.model.play(reply("seed answer"))
    run(go())


def test_a_message_queued_on_the_lock_behind_her_final_store_starts_a_turn_of_its_own(world: World) -> None:
    """Her final store holds the queue's head and the other pod's message waits behind it: her answer is stored
    first, the message sees no work and is answered by a turn of its own, once."""
    async def go() -> None:
        async with pods(world):
            sent: list[asyncio.Task[object]] = []

            async def take_the_lock() -> None:
                cid = world.thread_conversation(f"bench:{world.bench.id}")
                conn = await AsyncConnection.connect(world.url)
                await conn.execute(LOCK.encode(), (cid,))

                async def queue_and_release() -> None:
                    await lock_waiters(world.url, 1)  # her final store waits on the lock
                    sent.append(asyncio.create_task(world.from_pod(2, world.bench_say("racing"))))
                    await lock_waiters(world.url, 2)
                    await conn.commit()
                    await conn.close()

                sent.append(asyncio.create_task(queue_and_release()))

            world.inflight[1].before_finish = take_the_lock
            world.model.play(reply("first answer"), reply("answer to racing"))
            await respond(world.bench_say("question"))
            await asyncio.wait_for(sent[0], 10)
            out = await asyncio.wait_for(sent[1], 10)
            assert getattr(out, "body") == "answer to racing" and getattr(out, "follows") is False
            assert world.model.steps == 2 and said(world.model.prompts[1]) == []
            assert [(a, t) for a, t, _ in world.talk()] == [("person", "question"), ("ashley", "first answer"),
                                                            ("person", "racing"), ("ashley", "answer to racing")]
            assert world.work() == 0

    run(go())
