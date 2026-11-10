"""PostgresMemory's write-job reads and bookkeeping: which conversations need a write, the watermark landing with the
ops or not at all, the failure streak, and the candidate facts the writer decides against."""

import asyncio
from datetime import UTC, datetime

import pytest
from ashley.conversations.model import Conversation, Kind as ConversationKind, Turn
from ashley.memory.memory import AlreadyWritten
from ashley.memory.model import Add, Invalidate, NewFact, Noop, Unwritten, Visibility
from ashley.memory.postgres import PostgresMemory
from ashley.memory.postgres_writes import mark_written

from conversations_support import POLICY, household, person, place_before_now, run, scalar
from memory_support import conversation, pool, say

AT = datetime(2026, 3, 1, tzinfo=UTC)
IDLE: dict[ConversationKind, float] = {kind: timing.idle_after_s for kind, timing in POLICY.timings.items()}
CHAT_IDLE = POLICY.timings["chat"].idle_after_s


def fact(owner: int | None, text: str, visibility: Visibility = "shared") -> NewFact:
    return NewFact(owner, owner, visibility, False, "preference", False, text)


def ids(found: tuple[Unwritten, ...]) -> tuple[tuple[int, int | None], ...]:
    return tuple((u.conversation_id, u.written_through) for u in found)


def idle_talk(url: str, home: int, *turns: str, ago: float = CHAT_IDLE + 1) -> tuple[int, tuple[int, ...]]:
    talk = conversation(url, home)
    ids = say(url, talk, *turns)
    place_before_now(url, talk, ago)
    return talk, ids


def facts_count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM facts"))


def watermark(url: str, talk: int) -> object:
    return scalar(url, "SELECT coalesce((SELECT written_turn_id FROM memory_writes WHERE conversation_id = %s), -1)",
                  (talk,))


def test_only_idle_or_closed_conversations_with_unwritten_person_turns_need_a_write(db_url: str) -> None:
    home = household(db_url)
    still_open = conversation(db_url, home)
    say(db_url, still_open, "I like tea")
    idle, (_, reply) = idle_talk(db_url, home, "I like coffee", "Noted")
    closed, _ = idle_talk(db_url, home, "I like cocoa", ago=POLICY.timings["chat"].closed_after_s + 1)
    empty = conversation(db_url, home)
    place_before_now(db_url, empty, CHAT_IDLE + 1)

    async def scenario() -> None:
        async with pool(db_url) as db:
            found = await PostgresMemory(db).unwritten(IDLE, 10, 3)
            assert ids(found) == ((closed, None), (idle, None)), "oldest first; open and empty skipped"
            assert found[1] == Unwritten(idle, home, None, reply), "its household and newest turn, hers included"
            assert ids(await PostgresMemory(db).unwritten(IDLE, 1, 3)) == ((closed, None),)

    run(scenario())


def test_a_written_conversation_needs_a_write_again_only_after_a_new_person_turn(db_url: str) -> None:
    home = household(db_url)
    talk, (_, reply) = idle_talk(db_url, home, "I like coffee", "Noted")

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            await memory.apply(home, talk, [Noop(None)], AT, written_through=reply)
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ()
            say(db_url, talk, "Thanks", "You're welcome")
            place_before_now(db_url, talk, CHAT_IDLE + 1)
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ((talk, reply),)

    run(scenario())


def test_a_new_turn_of_hers_alone_does_not_need_a_write(db_url: str) -> None:
    home = household(db_url)
    talk, (first,) = idle_talk(db_url, home, "I like coffee")

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            await memory.apply(home, talk, [], AT, written_through=first)
            scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'ashley', 'Enjoy') RETURNING id", (talk, home))
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ()

    run(scenario())


def test_a_refused_apply_leaves_neither_facts_nor_watermark(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "alana")
    talk, (turn,) = idle_talk(db_url, home, "I like coffee")

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            with pytest.raises(ValueError):
                await memory.apply(home, talk, [Add(fact(alana, "Alana likes coffee")), Invalidate(999_999)], AT,
                                   written_through=turn)
            assert (facts_count(db_url), watermark(db_url, talk)) == (0, -1)
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ((talk, None),)

    run(scenario())


def test_the_same_turns_are_never_written_twice(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "alana")
    talk, (turn,) = idle_talk(db_url, home, "I like coffee")

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            await memory.apply(home, talk, [Add(fact(alana, "Alana likes coffee"))], AT, written_through=turn)
            for through in (turn, turn - 1):
                with pytest.raises(AlreadyWritten):
                    await memory.apply(home, talk, [Add(fact(alana, "Alana likes coffee"))], AT, written_through=through)
            assert (facts_count(db_url), watermark(db_url, talk)) == (1, turn)

    run(scenario())


def test_failures_in_a_row_hold_a_conversation_back_until_a_newer_person_turn(db_url: str) -> None:
    home = household(db_url)
    talk, (turn,) = idle_talk(db_url, home, "I like coffee")

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            assert [await memory.write_failed(home, talk, turn) for _ in range(2)] == [1, 2]
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ((talk, None),), "under the cap it is retried"
            assert await memory.write_failed(home, talk, turn) == 3
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ()
            (newer,) = say(db_url, talk, "Actually tea")
            place_before_now(db_url, talk, CHAT_IDLE + 1)
            assert ids(await memory.unwritten(IDLE, 10, 3)) == ((talk, None),)
            assert await memory.write_failed(home, talk, newer) == 1, "a failure on newer turns starts a new run"
            await memory.apply(home, talk, [], AT, written_through=newer)
            assert scalar(db_url, "SELECT failures FROM memory_writes WHERE conversation_id = %s", (talk,)) == 0

    run(scenario())


def test_a_conversation_of_another_household_is_refused_as_value_error(db_url: str) -> None:
    home, away = household(db_url), household(db_url, "away")
    talk, (turn,) = idle_talk(db_url, home, "I like coffee")

    async def scenario() -> None:
        async with pool(db_url) as db:
            with pytest.raises(ValueError):
                await PostgresMemory(db).apply(away, talk, [], AT, written_through=turn)
            assert watermark(db_url, talk) == -1

    run(scenario())


def _conversation(home: int, *turns: tuple[str, str]) -> Conversation:
    return Conversation(1, home, "chat", frozenset(), AT, AT, "idle",
                        tuple(Turn(i, "person" if a == "p" else "ashley", None, text, AT)
                              for i, (a, text) in enumerate(turns, 1)))


def test_candidates_are_current_facts_of_the_household_at_any_visibility(db_url: str) -> None:
    home, away = household(db_url), household(db_url, "away")
    alana, elodie, stranger = person(db_url, home, "alana"), person(db_url, home, "elodie"), person(db_url, away, "x")
    talk, away_talk = conversation(db_url, home), conversation(db_url, away)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            shared, private, closed, unrelated = await memory.apply(home, talk, [
                Add(fact(alana, "Alana drinks coffee every morning")),
                Add(fact(elodie, "Elodie's coffee order is private", "private")),
                Add(fact(alana, "Alana drank coffee black")),
                Add(fact(alana, "Mochi sleeps on the radiator"))], AT)
            await memory.apply(home, talk, [Invalidate(closed)], AT)
            await memory.apply(away, away_talk, [Add(fact(stranger, "Coffee is brewed at seven"))], AT)
            asked = _conversation(home, ("p", "We are out of coffee"), ("a", "radiator radiator"))
            assert {f.id for f in await memory.similar(asked, 10)} == {shared, private}
            assert unrelated not in {f.id for f in await memory.similar(asked, 10)}, "her turns are not searched"
            assert len(await memory.similar(asked, 1)) == 1
            assert await memory.similar(_conversation(home, ("a", "coffee")), 10) == ()

    run(scenario())


def test_two_writers_over_the_same_watermark_cannot_both_land(db_url: str) -> None:
    home = household(db_url)
    talk, (first, second) = idle_talk(db_url, home, "I like coffee", "and tea")

    async def scenario() -> None:
        async with pool(db_url) as db:
            async with db.connection() as holder, db.connection() as waiter:
                assert await mark_written(holder, home, talk, first, None)
                racing = asyncio.create_task(mark_written(waiter, home, talk, second, None))
                await asyncio.sleep(0.2)
                assert not racing.done(), "the second waits on the first's row lock"
                await holder.commit()
                assert not await racing, "and finds the watermark moved from where it decided"
        assert watermark(db_url, talk) == first

    run(scenario())


def test_an_apply_decided_from_a_watermark_that_moved_is_stale(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "alana")
    talk, (first, second) = idle_talk(db_url, home, "I like coffee", "and tea")

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            landed = await asyncio.gather(
                *(memory.apply(home, talk, [Add(fact(alana, "Alana likes coffee"))], AT, through, None)
                  for through in (first, second)), return_exceptions=True)
            assert sorted(type(r).__name__ for r in landed) == ["AlreadyWritten", "tuple"]
            assert facts_count(db_url) == 1

    run(scenario())
