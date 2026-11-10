"""`Conversations.for_thread`: a thread continues the conversation it last carried while that is open or idle by the
database's clock, and starts a new one (pointing the thread at it) when it is closed, never seen, or another
household's; it raises what `start` raises and writes nothing when it does; it logs `conversation.thread`."""

import pytest
from ashley import logs
from ashley.conversations.conversations import UnknownHousehold, UnknownPerson
from ashley.conversations.model import Kind, NewTurn
from conversations_support import KINDS, POLICY, events, household, person, place_before_now, run, service
from threads_support import ANY_KIND, conversation_count, everything, point, target


def test_a_thread_never_seen_starts_a_conversation_and_points_at_it(db_url: str) -> None:
    home = household(db_url)
    mine, yours = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            got = await conv.for_thread(home, "device:7", "chat", [mine, yours, mine])
            stored = await conv.get(got.id)
        assert got.turns == () and got.state == "open"
        assert got.household_id == home and got.kind == "chat"
        assert got.participants == frozenset({mine, yours})
        assert got.last_activity_at == got.started_at
        assert stored == got
        assert target(db_url, "device:7") == got.id

    run(scenario())


def test_an_open_thread_continues_its_conversation_ignoring_kind_and_participants(db_url: str) -> None:
    home = household(db_url)
    mine, yours = person(db_url, home), person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "device:7", "chat", [mine])
            await conv.add_turn(first.id, NewTurn("person", "hello", mine))
            await conv.add_turn(first.id, NewTurn("ashley", "hi"))
            again = await conv.for_thread(home, "device:7", "command", [yours])
            stored = await conv.get(first.id)
        assert again.id == first.id
        assert again.kind == "chat"
        assert again.participants == frozenset({mine})
        assert stored is not None and again == stored
        assert [t.text for t in again.turns] == ["hello", "hi"]
        assert conversation_count(db_url) == 1

    run(scenario())


def test_continuing_ignores_participants_even_ones_another_household_owns(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url)
    theirs = person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "t", "chat", [])
            again = await conv.for_thread(home, "t", "chat", [theirs])
        assert again.id == first.id and again.participants == frozenset()

    run(scenario())


def test_an_idle_thread_continues_and_reads_idle(db_url: str) -> None:
    home = household(db_url)
    timing = POLICY.timings["command"]

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "t", "command", [])
            place_before_now(db_url, first.id, (timing.idle_after_s + timing.closed_after_s) / 2)
            again = await conv.for_thread(home, "t", "command", [])
        assert again.id == first.id
        assert again.state == "idle"

    run(scenario())


@pytest.mark.parametrize("kind", KINDS)
def test_a_closed_thread_starts_a_new_conversation_and_repoints(db_url: str, kind: Kind) -> None:
    """Closed by the conversation's own kind: 1.5x its closing time, which every slower kind reads as open or idle
    (thresholds a decade apart), so judging by another kind's timing would continue it."""
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "t", kind, [mine])
            await conv.add_turn(first.id, NewTurn("person", "earlier", mine))
            place_before_now(db_url, first.id, POLICY.timings[kind].closed_after_s * 1.5)
            fresh = await conv.for_thread(home, "t", "brainstorm", [])
            after = await conv.for_thread(home, "t", "chat", [mine])
        assert fresh.id != first.id
        assert fresh.turns == () and fresh.state == "open"
        assert fresh.kind == "brainstorm" and fresh.participants == frozenset()
        assert target(db_url, "t") == fresh.id
        assert after.id == fresh.id

    run(scenario())


def test_a_thread_last_carrying_another_households_conversation_carries_none(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            theirs = await conv.for_thread(elsewhere, "shared-key", "chat", [])
            await conv.add_turn(theirs.id, NewTurn("ashley", "theirs"))
            mine = await conv.for_thread(home, "shared-key", "chat", [])
            stored = await conv.get(theirs.id)
        assert mine.id != theirs.id
        assert mine.household_id == home and mine.turns == ()
        assert target(db_url, "shared-key") == mine.id
        assert stored is not None and [t.text for t in stored.turns] == ["theirs"], "theirs is left as it was"

    run(scenario())


def test_several_threads_may_carry_one_conversation(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "discord:1", "chat", [])
            point(db_url, "discord:2", home, first.id)
            other = await conv.for_thread(home, "discord:2", "chat", [])
        assert other.id == first.id

    run(scenario())


def test_threads_are_independent(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            one = await conv.for_thread(home, "device:1", "chat", [])
            two = await conv.for_thread(home, "device:1:probe", "chat", [])
            again = await conv.for_thread(home, "device:1", "chat", [])
        assert one.id != two.id and again.id == one.id

    run(scenario())


def test_an_empty_thread_is_a_value_error_and_writes_nothing(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            before = everything(db_url)
            with pytest.raises(ValueError):
                await conv.for_thread(home, "", "chat", [])
            assert everything(db_url) == before

    run(scenario())


def test_raises_what_start_raises_and_writes_nothing(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url)
    theirs = person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            before = everything(db_url)
            with pytest.raises(ValueError):
                await conv.for_thread(home, "t", ANY_KIND, [])
            with pytest.raises(UnknownHousehold):
                await conv.for_thread(987_654_321, "t", "chat", [])
            with pytest.raises(UnknownPerson):
                await conv.for_thread(home, "t", "chat", [theirs])
            assert everything(db_url) == before

    run(scenario())


def test_a_refused_restart_of_a_closed_thread_leaves_the_thread_as_it_was(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url)
    theirs = person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "t", "command", [])
            place_before_now(db_url, first.id, POLICY.timings["command"].closed_after_s * 2)
            before = everything(db_url)
            with pytest.raises(UnknownPerson):
                await conv.for_thread(home, "t", "command", [theirs])
            assert everything(db_url) == before
            assert target(db_url, "t") == first.id

    run(scenario())


def test_logs_thread_continued_or_started(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    logs.setup()
    ids: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            for _ in range(3):   # ids past 1, so an id cannot be mistaken for anything else on the line
                await conv.start(home, "chat", [])
            capsys.readouterr()
            ids.append((await conv.for_thread(home, "device:9", "chat", [])).id)
            ids.append((await conv.for_thread(home, "device:9", "chat", [])).id)

    run(scenario())
    out = capsys.readouterr().out
    lines = events(out, "conversation.thread")
    assert len(lines) == 2
    assert {str(ids[0]), "started"} <= set(lines[0].values())
    assert {str(ids[1]), "continued"} <= set(lines[1].values())
    assert "started" not in lines[1].values() and "continued" not in lines[0].values()
    started = events(out, "conversation.started")
    assert len(started) == 1 and str(ids[0]) in started[0].values()
