"""Remembering one line now (`ashley.memory.remember`) over real Postgres, with a scripted writer behind the locator:
which turns the writer sees, where the watermark goes, and that the write job afterwards takes only the turns after it."""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Conversation
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.memory.memory import FactWriter, Memory
from ashley.memory.model import Add, Fact, Forget, Invalidate, NewFact, Op, Update
from ashley.memory.remember import RememberRefused, RememberUnavailable, remember
from ashley.memory.write_job import WriteJob
from conversations_support import POLICY, household, person, place_before_now, run, scalar
from memory_support import conversation, say
from test_memory_write_job import IDLE, JOB, facts_from, watermark, wired


class Writer(FactWriter):
    """Answers `ops` (or raises `error`) and records the turn ids of every conversation it was asked about."""

    def __init__(self, ops: tuple[Op, ...] = (), error: Exception | None = None) -> None:
        self.ops = ops
        self.error = error
        self.seen: list[tuple[int, ...]] = []
        self.known: list[tuple[int, ...]] = []

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        self.seen.append(tuple(t.id for t in conversation.turns))
        self.known.append(tuple(f.id for f in known))
        if self.error is not None:
            raise self.error
        return self.ops


def fact(text: str) -> Add:
    return Add(NewFact(None, None, "shared", False, "home", False, text))


@asynccontextmanager
async def with_writer(url: str, writer: Writer) -> AsyncGenerator[Conversations]:
    async with wired(url):
        services.register(FactWriter, writer)
        try:
            yield services.get(Conversations)
        finally:
            services.unregister(FactWriter)


def talk(url: str, *turns: str) -> tuple[int, int, tuple[int, ...]]:
    home = household(url)
    alana = person(url, home, "Alana")
    made = conversation(url, home)
    return made, home, say(url, made, *turns, speaker=alana)


def test_an_unwritten_line_is_written_with_the_lines_before_it_and_moves_the_watermark(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi", "noted", "she eats at six", "ok", "and the dog is Rex")
    writer = Writer((fact("Mochi eats at six"),))

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            done = await remember(read, ids[2])
            assert len(done.inserted) == 1 and done.ended == 0
    run(scenario())
    assert writer.seen == [ids[:3]]
    assert watermark(db_url, made) == ids[2]
    assert facts_from(db_url, made) == 1


def test_the_job_then_takes_only_the_turns_after_it(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi", "noted", "she eats at six", "ok", "and the dog is Rex")
    writer = Writer((fact("Mochi eats at six"),))

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            await remember(read, ids[2])
            place_before_now(db_url, made, IDLE)
            await WriteJob(writer, JOB, POLICY).tick()
    run(scenario())
    assert writer.seen == [ids[:3], ids[3:]]
    assert watermark(db_url, made) == ids[4]


def test_a_line_already_written_is_decided_with_the_turn_before_it_and_leaves_the_watermark(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi", "noted", "she eats at six", "ok")
    writer = Writer()

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            writer.ops = (fact("Mochi is a cat"),)
            await remember(read, ids[3])
            writer.ops = ()
            done = await remember(read, ids[1])
            assert done.inserted == () and done.ended == 0
    run(scenario())
    assert writer.seen == [ids, ids[:2]]
    assert watermark(db_url, made) == ids[3]


def test_a_correction_counts_as_replaced_and_a_forget_as_ended(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi and the dog is Rex", "noted", "Mochi is a kitten, and forget Rex")
    writer = Writer((fact("Mochi is a cat"), fact("The dog is Rex")))

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            cat, dog = (await remember(read, ids[0])).inserted
            writer.ops = (Update(cat, fact("Mochi is a kitten").fact), Forget(dog))
            done = await remember(read, ids[2])
            assert (len(done.inserted), done.replaced, done.ended) == (1, 1, 1)
    run(scenario())


def test_a_line_the_writer_learns_nothing_from_still_moves_the_watermark(db_url: str) -> None:
    made, _, ids = talk(db_url, "hello", "hi")

    async def scenario() -> None:
        async with with_writer(db_url, Writer()) as conversations:
            read = await conversations.get(made)
            assert read is not None
            assert (await remember(read, ids[1])).inserted == ()
    run(scenario())
    assert watermark(db_url, made) == ids[1]
    assert facts_from(db_url, made) == 0


@pytest.mark.parametrize(("error", "raised"), [(InferenceUnavailable("down"), RememberUnavailable),
                                                (InferenceRefused("no"), RememberRefused)])
def test_a_writer_that_cannot_answer_applies_nothing(db_url: str, error: Exception, raised: type[Exception]) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi")

    async def scenario() -> None:
        async with with_writer(db_url, Writer(error=error)) as conversations:
            read = await conversations.get(made)
            assert read is not None
            with pytest.raises(raised):
                await remember(read, ids[0])
    run(scenario())
    assert watermark(db_url, made) == -1


def test_a_stale_target_twice_running_is_unavailable_and_applies_nothing(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is gone")
    writer = Writer((Invalidate(999999),))

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            with pytest.raises(RememberUnavailable):
                await remember(read, ids[0])
    run(scenario())
    assert writer.seen == [ids, ids]
    assert watermark(db_url, made) == -1


def test_a_turn_outside_the_conversation_is_a_value_error(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi")
    writer = Writer()

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            with pytest.raises(ValueError):
                await remember(read, ids[0] + 1000)
    run(scenario())
    assert writer.seen == []


def test_a_line_the_job_wrote_part_of_meanwhile_is_decided_again_from_the_new_watermark(db_url: str) -> None:
    made, home, ids = talk(db_url, "the cat is Mochi", "noted", "she eats at six")

    class Raced(Writer):
        async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
            if not self.seen:
                scalar(db_url, "INSERT INTO memory_writes (conversation_id, household_id, written_turn_id) "
                               "VALUES (%s, %s, %s) RETURNING 1", (made, home, ids[0]))
            return await super().decide(conversation, known, now)

    writer = Raced((fact("Mochi eats at six"),))

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            assert len((await remember(read, ids[2])).inserted) == 1
    run(scenario())
    assert writer.seen == [ids, ids[1:]]
    assert watermark(db_url, made) == ids[2]
    assert facts_from(db_url, made) == 1


def test_the_turn_that_answered_the_line_is_decided_with_it_and_the_watermark_moves_to_it(db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi", "noted", "she eats at six", "ok, she eats at six", "and the dog is Rex")
    writer = Writer()

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            await remember(read, ids[2], ids[3])
    run(scenario())
    assert writer.seen == [ids[:4]]
    assert watermark(db_url, made) == ids[3]


def test_a_line_already_written_is_decided_again_with_the_turn_before_it_and_the_one_that_answered_it(
        db_url: str) -> None:
    made, _, ids = talk(db_url, "the cat is Mochi", "noted", "she eats at six", "ok, six", "and the dog is Rex")
    writer = Writer()

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            read = await conversations.get(made)
            assert read is not None
            await remember(read, ids[4])
            await remember(read, ids[2], ids[3])
    run(scenario())
    assert writer.seen == [ids, ids[1:4]]
    assert watermark(db_url, made) == ids[4]


def test_the_facts_a_line_is_about_are_among_those_the_writer_decides_against(
        db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    made, _, ids = talk(db_url, "the shed code is 6190", "noted", "forget that, we changed it", "ok")
    writer = Writer((fact("The shed code is 6190"),))

    async def nothing_is_like_it(*_: object) -> tuple[Fact, ...]:
        return ()

    code: list[int] = []

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            monkeypatch.setattr(services.get(Memory), "similar", nothing_is_like_it)
            read = await conversations.get(made)
            assert read is not None
            code.extend((await remember(read, ids[0])).inserted)
            await remember(read, ids[2], ids[3], (code[0],))
            await remember(read, ids[2], ids[3], (code[0] + 1000,))
    run(scenario())
    assert writer.known == [(), (code[0],), ()]


def test_a_fact_the_speaker_may_not_see_is_never_handed_to_the_writer(
        db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    home = household(db_url)
    alana, ella = person(db_url, home, "Alana"), person(db_url, home, "Ella")
    made = conversation(db_url, home)
    ids = say(db_url, made, "forget Ella's diary", "ok", speaker=alana)
    secret = Add(NewFact(ella, ella, "private", True, "other", False, "Ella keeps a diary"))
    writer = Writer((secret,))

    async def nothing_is_like_it(*_: object) -> tuple[Fact, ...]:
        return ()

    hidden: list[int] = []

    async def scenario() -> None:
        async with with_writer(db_url, writer) as conversations:
            monkeypatch.setattr(services.get(Memory), "similar", nothing_is_like_it)
            other = conversation(db_url, home)
            theirs = say(db_url, other, "I keep a diary", "ok", speaker=ella)
            read_other = await conversations.get(other)
            assert read_other is not None
            hidden.extend((await remember(read_other, theirs[0])).inserted)
            read = await conversations.get(made)
            assert read is not None
            await remember(read, ids[0], ids[1], tuple(hidden))
    run(scenario())
    assert hidden and writer.known[-1] == ()
