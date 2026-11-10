"""Household isolation and validation: a person from another household can neither take part nor speak, an unknown
household or person is refused, and malformed input is refused with ValueError before the database is touched. Nothing
is written when a call raises."""

from typing import Any

import pytest
from ashley.conversations.conversations import UnknownHousehold, UnknownPerson
from ashley.conversations.model import Kind, NewTurn
from conversations_support import TouchDatabase, footprint, household, make, person, run, service
from hypothesis import given, settings
from hypothesis import strategies as st


def test_a_participant_from_another_household_is_refused_and_nothing_is_written(db_url: str) -> None:
    home, elsewhere = household(db_url, "home"), household(db_url, "elsewhere")
    mine, theirs = person(db_url, home), person(db_url, elsewhere)
    before = footprint(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            for participants in ([theirs], [mine, theirs], [theirs, mine], [mine, mine, theirs]):
                with pytest.raises(UnknownPerson):
                    await conv.start(home, "chat", participants)

    run(scenario())
    assert footprint(db_url) == before


def test_a_participant_who_is_no_person_is_refused_and_nothing_is_written(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)
    before = footprint(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            for participants in ([987_654_321], [mine, 987_654_321]):
                with pytest.raises(UnknownPerson):
                    await conv.start(home, "command", participants)

    run(scenario())
    assert footprint(db_url) == before


def test_an_unknown_household_is_refused_and_nothing_is_written(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)
    before = footprint(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            with pytest.raises(UnknownHousehold):
                await conv.start(987_654_321, "chat", [])
            with pytest.raises((UnknownHousehold, UnknownPerson)):
                await conv.start(987_654_321, "chat", [mine])

    run(scenario())
    assert footprint(db_url) == before


def test_a_speaker_from_another_household_is_refused_and_does_not_join(db_url: str) -> None:
    home, elsewhere = household(db_url, "home"), household(db_url, "elsewhere")
    mine, theirs = person(db_url, home), person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", [mine])
            before = footprint(db_url)
            with pytest.raises(UnknownPerson):
                await conv.add_turn(started.id, NewTurn("person", "let me in", theirs))
            assert footprint(db_url) == before
            got = await conv.get(started.id)
            assert got is not None and (got.participants, got.turns) == (frozenset({mine}), ())

    run(scenario())


def test_each_household_s_people_speak_in_their_own_conversations(db_url: str) -> None:
    """The control for the refusals above: the same people are accepted in their own household."""
    home, elsewhere = household(db_url, "home"), household(db_url, "elsewhere")
    mine, theirs = person(db_url, home), person(db_url, elsewhere)

    async def scenario() -> None:
        async with service(db_url) as conv:
            here = await conv.start(home, "chat", [mine])
            there = await conv.start(elsewhere, "chat", [theirs])
            await conv.add_turn(there.id, NewTurn("person", "hi", theirs))
            got_here, got_there = await conv.get(here.id), await conv.get(there.id)
            assert got_here is not None and got_there is not None
            assert (got_here.household_id, got_here.participants, got_here.turns) == (home, frozenset({mine}), ())
            assert (got_there.household_id, got_there.participants) == (elsewhere, frozenset({theirs}))
            assert len(got_there.turns) == 1

    run(scenario())


# --- validation before the database -----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["smalltalk", "", "Chat", "COMMAND", " chat"])
def test_a_kind_outside_kind_is_refused_before_the_database(kind: Any) -> None:
    """`kind` is typed Any because a value outside `Kind` is the case under test."""
    db = TouchDatabase()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await make(db).start(1, kind, [])

    run(scenario())
    assert db.touched == 0


def bad_turns() -> list[NewTurn]:
    return [NewTurn("ashley", "hello", 1), NewTurn("person", ""), NewTurn("person", "", 1), NewTurn("ashley", ""),
            NewTurn("person", "   "), NewTurn("person", "\n\t \r", 1), NewTurn("ashley", "\f\v")]


@pytest.mark.parametrize("turn", bad_turns(), ids=repr)
def test_a_malformed_turn_is_refused_before_the_database(turn: NewTurn) -> None:
    db = TouchDatabase()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await make(db).add_turn(1, turn)

    run(scenario())
    assert db.touched == 0


@settings(max_examples=40, deadline=None)
@given(text=st.text(alphabet=" \t\n\r\f\v", max_size=12), author=st.sampled_from(["person", "ashley"]))
def test_any_whitespace_only_text_is_refused_before_the_database(text: str, author: str) -> None:
    db = TouchDatabase()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await make(db).add_turn(1, NewTurn("person" if author == "person" else "ashley", text))

    run(scenario())
    assert db.touched == 0


def test_a_malformed_turn_to_a_real_conversation_writes_nothing(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", [])
            before = footprint(db_url)
            for turn in (NewTurn("ashley", "hi", mine), NewTurn("person", " ", mine)):
                with pytest.raises(ValueError):
                    await conv.add_turn(started.id, turn)
            assert footprint(db_url) == before

    run(scenario())


@pytest.mark.parametrize("kind", ["command", "chat", "brainstorm"])
def test_a_valid_call_does_reach_the_database(kind: Kind) -> None:
    """The control for the before-the-database tests: the probe sees a call that has to go to the database."""
    db = TouchDatabase()

    async def scenario() -> None:
        conv = make(db)
        for call in (conv.start(1, kind, []), conv.add_turn(1, NewTurn("person", "hi")), conv.get(1)):
            with pytest.raises(BaseException):
                await call

    run(scenario())
    assert db.touched >= 3
