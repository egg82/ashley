"""Conversations round trips through `PostgresConversations`: start, add_turn and get as the interface documents them,
the state as of the read by the database's clock, idle reopening and closed refusal, nothing written on a raise."""

from datetime import timedelta

import pytest
from ashley.conversations.conversations import ConversationClosed, ConversationNotFound, UnknownPerson
from ashley.conversations.model import Conversation, Kind, NewTurn
from ashley.conversations.policy import Policy
from conversations_support import KINDS, POLICY, db_now, footprint, household, person, place_before_now, run, service

SLACK = timedelta(seconds=5)


async def reread(url: str, conversation_id: int) -> Conversation:
    async with service(url) as conv:
        found = await conv.get(conversation_id)
    assert found is not None
    return found


@pytest.mark.parametrize("kind", KINDS)
def test_start_returns_the_conversation_as_stored_and_get_reads_it_back(db_url: str, kind: Kind) -> None:
    home = household(db_url)
    a, b = person(db_url, home), person(db_url, home)
    before = db_now(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, kind, [a, b])
            assert (started.household_id, started.kind, started.participants) == (home, kind, frozenset({a, b}))
            assert (started.state, started.turns) == ("open", ())
            assert started.last_activity_at == started.started_at
            assert started.started_at.utcoffset() == timedelta(0)
            assert before - SLACK <= started.started_at <= db_now(db_url) + SLACK
            assert await conv.get(started.id) == started

    run(scenario())


def test_every_start_s_last_activity_is_exactly_its_start(db_url: str) -> None:
    """Many starts, so two clock readings a microsecond apart cannot pass by luck."""
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            for i in range(30):
                started = await conv.start(home, KINDS[i % 3], [])
                got = await conv.get(started.id)
                assert got is not None
                assert started.last_activity_at == started.started_at == got.last_activity_at == got.started_at

    run(scenario())


def test_participants_may_be_empty_or_repeat_an_id(db_url: str) -> None:
    home = household(db_url)
    a, b = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            empty = await conv.start(home, "command", [])
            repeated = await conv.start(home, "chat", [a, b, a, a])
            assert empty.participants == frozenset()
            assert repeated.participants == frozenset({a, b})
            assert empty.id != repeated.id
            assert (await reread(db_url, empty.id)).participants == frozenset()
            assert (await reread(db_url, repeated.id)).participants == frozenset({a, b})

    run(scenario())


def test_participants_accept_any_iterable_once(db_url: str) -> None:
    home = household(db_url)
    a, b = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", (p for p in [a, b]))
            assert started.participants == frozenset({a, b})

    run(scenario())


def test_turns_are_stored_oldest_first_and_move_last_activity(db_url: str) -> None:
    home = household(db_url)
    a = person(db_url, home)
    said = ["Turn on the porch light", "Mochi the cat — fed?\nyes", "done"]

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", [a])
            added = [await conv.add_turn(started.id, NewTurn("person", said[0], a)),
                     await conv.add_turn(started.id, NewTurn("ashley", said[1])),
                     await conv.add_turn(started.id, NewTurn("person", said[2]))]
            got = await conv.get(started.id)
        assert got is not None
        assert got.turns == tuple(added)
        assert [t.text for t in got.turns] == said
        assert [(t.author, t.speaker_id) for t in got.turns] == [("person", a), ("ashley", None), ("person", None)]
        assert len({t.id for t in added}) == 3
        assert [t.id for t in added] == sorted(t.id for t in added)
        assert [t.at for t in added] == sorted(t.at for t in added)
        assert all(t.at.utcoffset() == timedelta(0) for t in added)
        assert started.started_at <= added[0].at
        assert got.last_activity_at == added[-1].at
        assert (got.started_at, got.state) == (started.started_at, "open")

    run(scenario())


def test_a_known_speaker_joins_and_an_unnamed_one_or_ashley_does_not(db_url: str) -> None:
    home = household(db_url)
    a, b = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", [a])
            await conv.add_turn(started.id, NewTurn("person", "who's there?"))
            await conv.add_turn(started.id, NewTurn("ashley", "hello"))
            assert (await reread(db_url, started.id)).participants == frozenset({a})
            await conv.add_turn(started.id, NewTurn("person", "me", b))
            await conv.add_turn(started.id, NewTurn("person", "me again", b))
            await conv.add_turn(started.id, NewTurn("person", "and me", a))
            assert (await reread(db_url, started.id)).participants == frozenset({a, b})

    run(scenario())


def test_a_first_speaker_joins_a_conversation_started_with_nobody(db_url: str) -> None:
    home = household(db_url)
    a = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "command", [])
            await conv.add_turn(started.id, NewTurn("person", "lights off", a))
            assert (await reread(db_url, started.id)).participants == frozenset({a})

    run(scenario())


def test_get_answers_none_for_an_id_no_conversation_has(db_url: str) -> None:
    async def scenario() -> None:
        async with service(db_url) as conv:
            assert await conv.get(1) is None
            assert await conv.get(987_654_321) is None
            assert await conv.get(-1) is None

    run(scenario())


def test_a_turn_to_no_conversation_is_refused_and_writes_nothing(db_url: str) -> None:
    home = household(db_url)
    a = person(db_url, home)
    before = footprint(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            with pytest.raises(ConversationNotFound):
                await conv.add_turn(987_654_321, NewTurn("person", "hello", a))

    run(scenario())
    assert footprint(db_url) == before


def test_a_speaker_who_is_no_person_is_refused_and_writes_nothing(db_url: str) -> None:
    home = household(db_url)
    a = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", [a])
            before = footprint(db_url)
            with pytest.raises(UnknownPerson):
                await conv.add_turn(started.id, NewTurn("person", "hello", 987_654_321))
            assert footprint(db_url) == before

    run(scenario())


@pytest.mark.parametrize(("seconds_ago", "expected"), [
    (5, {"command": "open", "chat": "open", "brainstorm": "open"}),
    (50, {"command": "idle", "chat": "open", "brainstorm": "open"}),
    (5_000, {"command": "closed", "chat": "idle", "brainstorm": "open"}),
    (500_000, {"command": "closed", "chat": "closed", "brainstorm": "idle"}),
    (5_000_000, {"command": "closed", "chat": "closed", "brainstorm": "closed"}),
])
def test_get_reports_the_state_its_kind_s_policy_gives_now(db_url: str, seconds_ago: float,
                                                            expected: dict[Kind, str]) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            ids = {k: (await conv.start(home, k, [])).id for k in KINDS}
            for cid in ids.values():
                place_before_now(db_url, cid, seconds_ago)
            assert {k: (await reread(db_url, cid)).state for k, cid in ids.items()} == expected

    run(scenario())


def test_the_state_follows_the_policy_the_service_was_given(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "brainstorm", [])).id
        place_before_now(db_url, cid, 50)
        loose = POLICY.timings["command"]
        async with service(db_url, Policy({k: loose for k in KINDS})) as conv:
            got = await conv.get(cid)
        assert got is not None and got.state == "idle"

    run(scenario())


@pytest.mark.parametrize("kind", KINDS)
def test_a_turn_to_an_idle_conversation_reopens_it(db_url: str, kind: Kind) -> None:
    home = household(db_url)
    a, b = person(db_url, home), person(db_url, home)
    t = POLICY.timings[kind]

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, kind, [a])).id
            place_before_now(db_url, cid, (t.idle_after_s + t.closed_after_s) / 2)
            idle = await conv.get(cid)
            assert idle is not None and idle.state == "idle"
            turn = await conv.add_turn(cid, NewTurn("person", "still there?", b))
            got = await conv.get(cid)
        assert got is not None
        assert got.state == "open"
        assert got.last_activity_at == turn.at > idle.last_activity_at
        assert got.turns == (turn,)
        assert got.participants == frozenset({a, b})

    run(scenario())


@pytest.mark.parametrize("kind", KINDS)
def test_a_turn_to_a_closed_conversation_is_refused_and_writes_nothing(db_url: str, kind: Kind) -> None:
    home = household(db_url)
    a, newcomer = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, kind, [a])).id
            await conv.add_turn(cid, NewTurn("person", "first", a))
            place_before_now(db_url, cid, POLICY.timings[kind].closed_after_s + 1)
            before, closed = footprint(db_url), await conv.get(cid)
            for turn in (NewTurn("person", "late", newcomer), NewTurn("ashley", "late"), NewTurn("person", "late")):
                with pytest.raises(ConversationClosed):
                    await conv.add_turn(cid, turn)
            assert footprint(db_url) == before
            assert await conv.get(cid) == closed
        assert closed is not None and closed.state == "closed" and len(closed.turns) == 1

    run(scenario())


def test_just_after_the_closing_moment_a_turn_is_refused(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "command", [])).id
            place_before_now(db_url, cid, POLICY.timings["command"].closed_after_s + 0.05)
            with pytest.raises(ConversationClosed):
                await conv.add_turn(cid, NewTurn("ashley", "too late"))

    run(scenario())


def test_well_before_the_closing_moment_a_turn_is_taken(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "command", [])).id
            place_before_now(db_url, cid, POLICY.timings["command"].closed_after_s - 5)
            turn = await conv.add_turn(cid, NewTurn("ashley", "just in time"))
            got = await conv.get(cid)
        assert got is not None and got.turns == (turn,) and got.state == "open"

    run(scenario())


def test_a_service_reads_what_another_instance_wrote(db_url: str) -> None:
    """No state in the process: a second instance (the other site) sees every turn the first stored."""
    home = household(db_url)
    a = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as one, service(db_url) as two:
            started = await one.start(home, "chat", [a])
            t1 = await two.add_turn(started.id, NewTurn("person", "from the kitchen", a))
            t2 = await one.add_turn(started.id, NewTurn("ashley", "heard you"))
            assert (await two.get(started.id)) == (await one.get(started.id))
            got = await two.get(started.id)
            assert got is not None and got.turns == (t1, t2)

    run(scenario())

