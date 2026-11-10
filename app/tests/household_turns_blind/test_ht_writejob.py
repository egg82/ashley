"""The memory write job never shows a household turn to the writer, and never counts one as new words."""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime

from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Conversation
from ashley.memory.memory import FactWriter, Memory
from ashley.memory.model import Add, Fact, NewFact, Op
from ashley.memory.postgres import PostgresMemory
from ashley.memory.write_job import Policy, WriteJob
from contract.conversations_support import POLICY, household, make, person, place_before_now, run, scalar
from ashley.db.pool import PoolDatabase

def conversation(url: str, household_id: int) -> int:
    return int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                      (household_id,)))


@asynccontextmanager
async def pool(url: str) -> AsyncGenerator[PoolDatabase]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield db
    finally:
        await db.close()


JOB = Policy(tick_s=0.01, batch=10, candidates=10, max_failures=2, embed_batch=10)
IDLE = POLICY.timings["chat"].idle_after_s + 1


class Recording(FactWriter):
    def __init__(self) -> None:
        self.seen: list[Conversation] = []

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        self.seen.append(conversation)
        return (Add(NewFact(None, None, "shared", False, "home", False, "A learned fact")),)


@asynccontextmanager
async def wired(url: str) -> AsyncGenerator[None]:
    async with pool(url) as db:
        services.register(Memory, PostgresMemory(db))
        services.register(Conversations, make(db))
        yield


def put(url: str, talk: int, author: str, text: str, speaker: int | None = None) -> None:
    scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text) "
                "SELECT id, household_id, %s, %s, %s FROM conversations WHERE id = %s RETURNING id",
           (author, speaker, text, talk))
    scalar(url, "UPDATE conversations SET last_activity_at = clock_timestamp() WHERE id = %s RETURNING id", (talk,))


def test_a_conversation_of_only_a_household_turn_and_her_reply_is_not_written(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    put(db_url, talk, "household", "alana_arrived · Alana · front_door")
    put(db_url, talk, "ashley", "Welcome home.")
    place_before_now(db_url, talk, IDLE)
    writer = Recording()

    async def scenario() -> None:
        async with wired(db_url):
            await WriteJob(writer, JOB, POLICY).tick()

    run(scenario())
    assert not any(any(t.author == "household" for t in c.turns) for c in writer.seen)
    assert scalar(db_url, "SELECT count(*) FROM facts WHERE source_conversation_id = %s", (talk,)) == 0


def test_the_writer_is_shown_the_persons_words_but_never_the_household_turn(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    talk = conversation(db_url, home)
    put(db_url, talk, "household", "alana_arrived · Alana · front_door")
    put(db_url, talk, "ashley", "Welcome home.")
    put(db_url, talk, "person", "I like the lamp on", alana)
    put(db_url, talk, "ashley", "Noted.")
    place_before_now(db_url, talk, IDLE)
    writer = Recording()

    async def scenario() -> None:
        async with wired(db_url):
            await WriteJob(writer, JOB, POLICY).tick()

    run(scenario())
    assert len(writer.seen) == 1
    shown = writer.seen[0].turns
    assert "I like the lamp on" in [t.text for t in shown]
    assert all(t.author != "household" and "alana_arrived" not in t.text for t in shown)


def test_a_household_turn_after_the_watermark_does_not_make_the_conversation_unwritten_again(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    talk = conversation(db_url, home)
    put(db_url, talk, "person", "I like the lamp on", alana)
    put(db_url, talk, "ashley", "Noted.")
    place_before_now(db_url, talk, IDLE)
    writer = Recording()

    async def first() -> None:
        async with wired(db_url):
            await WriteJob(writer, JOB, POLICY).tick()

    run(first())
    assert len(writer.seen) == 1
    put(db_url, talk, "household", "alana_left · Alana · front_door")
    place_before_now(db_url, talk, IDLE)

    async def second() -> None:
        async with wired(db_url):
            await WriteJob(writer, JOB, POLICY).tick()

    run(second())
    assert len(writer.seen) == 1
