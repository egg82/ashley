"""Concurrency: concurrent turns to one conversation are all stored, each with its own id, in commit order; a turn
racing the closing moment is either stored with the conversation reopened or refused, never stored into a conversation
that had closed."""

import asyncio
from datetime import datetime, timedelta

import pytest
from ashley.conversations.conversations import ConversationClosed
from ashley.conversations.model import Conversation, NewTurn, Turn
from conversations_support import (POLICY, blocked_backend, footprint, gather_settled, holding, household, person,
                                   place_before_now, run, service)


def assert_never_stored_after_closing(got: Conversation, closed_after: timedelta) -> None:
    """Every turn arrived while the conversation was open or idle: within `closed_after` of the activity before it."""
    previous = got.started_at
    for turn in got.turns:
        assert turn.at - previous < closed_after, f"turn {turn.id} stored {turn.at - previous} after the last activity"
        previous = turn.at


@pytest.mark.parametrize("round_", range(2))
def test_concurrent_turns_are_all_stored_with_distinct_ids_in_order(db_url: str, round_: int) -> None:
    home = household(db_url)
    people = [person(db_url, home) for _ in range(4)]
    n = 24

    async def scenario() -> None:
        async with service(db_url) as conv, service(db_url) as other_site:
            cid = (await conv.start(home, "chat", [])).id
            calls = [(conv if i % 2 else other_site).add_turn(
                cid, NewTurn("person", f"turn {i}", people[i % 4]) if i % 3 else NewTurn("ashley", f"turn {i}"))
                for i in range(n)]
            results = await gather_settled(*calls)
            got = await conv.get(cid)
        stored = [r for r in results if isinstance(r, Turn)]
        assert stored == results, [r for r in results if not isinstance(r, Turn)]
        assert got is not None
        assert len({t.id for t in stored}) == n
        assert set(got.turns) == set(stored)
        assert len(got.turns) == n
        assert sorted(t.text for t in got.turns) == sorted(f"turn {i}" for i in range(n))
        assert [t.at for t in got.turns] == sorted(t.at for t in got.turns), "turns are not oldest first"
        assert got.last_activity_at == max(t.at for t in got.turns) == got.turns[-1].at
        assert got.participants == frozenset(people)

    run(scenario())


def test_concurrent_starts_each_make_their_own_conversation(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            made = await gather_settled(*(conv.start(home, "command", [mine, mine]) for _ in range(12)))
            assert all(isinstance(c, Conversation) for c in made), made
            ids = {c.id for c in made if isinstance(c, Conversation)}
            assert len(ids) == 12
            for cid in ids:
                got = await conv.get(cid)
                assert got is not None and got.participants == frozenset({mine})

    run(scenario())


async def closing_moment(url: str, conversation_id: int) -> datetime:
    async with service(url) as conv:
        got = await conv.get(conversation_id)
    assert got is not None and got.state == "idle"
    return got.last_activity_at + timedelta(seconds=POLICY.timings["command"].closed_after_s)


@pytest.mark.parametrize("round_", range(2))
def test_a_turn_held_up_past_the_closing_moment_is_never_stored_into_a_closed_conversation(db_url: str,
                                                                                           round_: int) -> None:
    """The turn is sent while the conversation is idle, a moment before it closes, and a second connection holds the
    conversation's row until the database's clock is past the closing moment. Taking it (reopened, recorded before
    closing) or refusing it are both right; storing it as arriving after closing is not."""
    home = household(db_url)
    closed_after = timedelta(seconds=POLICY.timings["command"].closed_after_s)

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "command", [])).id
            place_before_now(db_url, cid, closed_after.total_seconds() - 0.4)
            closing = await closing_moment(db_url, cid)
            before = footprint(db_url)
            async with holding(db_url, "SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (cid,)) as lock:
                call = asyncio.create_task(conv.add_turn(cid, NewTurn("ashley", "just in time?")))
                await blocked_backend(db_url)
                await lock.execute("SELECT pg_sleep(greatest(0, extract(epoch FROM %s - clock_timestamp())) + 0.1)",
                                   (closing,))
            outcome = await gather_settled(call)
            got = await conv.get(cid)
        assert got is not None
        if isinstance(outcome[0], ConversationClosed):
            assert footprint(db_url) == before
            assert got.turns == () and got.state == "closed"
        else:
            assert isinstance(outcome[0], Turn), outcome[0]
            assert got.turns == (outcome[0],)
            assert_never_stored_after_closing(got, closed_after)
            assert got.last_activity_at == outcome[0].at
            assert got.state == "open"

    run(scenario())


def test_two_turns_racing_the_closing_moment_never_both_land_after_it(db_url: str) -> None:
    """Two turns from two instances, both held until past the closing moment: whichever are stored were recorded while
    the conversation was still open or idle, each within the closing time of the activity before it."""
    home = household(db_url)
    closed_after = timedelta(seconds=POLICY.timings["command"].closed_after_s)

    async def scenario() -> None:
        async with service(db_url) as one, service(db_url) as two:
            cid = (await one.start(home, "command", [])).id
            place_before_now(db_url, cid, closed_after.total_seconds() - 0.4)
            closing = await closing_moment(db_url, cid)
            async with holding(db_url, "SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (cid,)) as lock:
                calls = [asyncio.create_task(c.add_turn(cid, NewTurn("ashley", f"from {i}")))
                         for i, c in enumerate((one, two))]
                await blocked_backend(db_url)
                await lock.execute("SELECT pg_sleep(greatest(0, extract(epoch FROM %s - clock_timestamp())) + 0.1)",
                                   (closing,))
            outcomes = await gather_settled(*calls)
            got = await one.get(cid)
        assert got is not None
        assert all(isinstance(o, (Turn, ConversationClosed)) for o in outcomes), outcomes
        assert set(got.turns) == {o for o in outcomes if isinstance(o, Turn)}
        assert_never_stored_after_closing(got, closed_after)

    run(scenario())
