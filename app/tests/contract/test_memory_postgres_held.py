"""Directed tests for PostgresMemory.held and .forget against a migrated database: which facts a person sees as theirs
to correct and forget, and that forgetting one leaves nothing of its supersede chain."""

from datetime import UTC, datetime

import pytest
from ashley import logs
from ashley.memory.model import Add, NewFact, Update, Visibility
from ashley.memory.postgres import PostgresMemory

from conversations_support import events, household, person, run, scalar
from memory_support import conversation, pool

AT = datetime(2026, 3, 1, tzinfo=UTC)
LATER = datetime(2026, 3, 2, tzinfo=UTC)


def new(about: int | None, owner: int | None, text: str, visibility: Visibility = "shared") -> NewFact:
    return NewFact(about, owner, visibility, True, "preference", False, text)


def take_part(url: str, conversation_id: int, person_id: int) -> None:
    scalar(url, "INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                "SELECT id, household_id, %s FROM conversations WHERE id = %s RETURNING person_id",
           (person_id, conversation_id))


def test_a_person_sees_what_is_about_them_theirs_or_the_households_and_nothing_hidden_from_them(db_url: str) -> None:
    home, away = household(db_url), household(db_url, "away")
    alana, ella = person(db_url, home, "alana"), person(db_url, home, "ella")
    talk, away_talk = conversation(db_url, home), conversation(db_url, away)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            about_me, mine_of_ella, house, discreet_about_me, closed = await memory.apply(home, talk, [
                Add(new(alana, alana, "Alana likes tea", "private")),
                Add(new(ella, alana, "Ella's birthday is in May")),
                Add(new(None, None, "Mochi is fed at six")),
                Add(new(alana, ella, "Alana is learning piano", "discreet")),
                Add(new(alana, alana, "Alana owns a kiln"))], AT)
            await memory.apply(home, talk, [
                Add(new(alana, ella, "Ella is planning Alana's party", "private")),
                Add(new(ella, ella, "Ella likes jazz")),
                Update(closed, new(alana, alana, "Alana sold the kiln"))], LATER)
            await memory.apply(away, away_talk, [Add(new(None, None, "Biscuit is fed at six"))], AT)
            (oldest,) = await memory.apply(home, talk, [Add(new(alana, alana, "Alana grew up in Ohio"))],
                                           datetime(2026, 1, 1, tzinfo=UTC))
            seen = await memory.held(home, alana)
            sold = seen[0].fact.id
            assert [h.fact.id for h in seen] == [sold, discreet_about_me, house, mine_of_ella, about_me, oldest]
            assert {h.fact.household_id for h in seen} == {home}
            assert [h.fact.id for h in await memory.held(home, alana, house)] == [house]
            assert await memory.held(home, alana, sold + 100) == ()

    run(scenario())


def test_the_fact_it_replaced_shows_only_when_the_person_may_see_it(db_url: str) -> None:
    home = household(db_url)
    alana, ella = person(db_url, home, "alana"), person(db_url, home, "ella")
    talk = conversation(db_url, home)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            tea, hidden = await memory.apply(home, talk, [
                Add(new(alana, alana, "Alana likes tea")), Add(new(alana, ella, "Ella thinks Alana is tired", "private"))], AT)
            coffee, rested = await memory.apply(home, talk, [
                Update(tea, new(alana, alana, "Alana likes coffee")),
                Update(hidden, new(alana, ella, "Alana is rested", "shared"))], LATER)
            by_id = {h.fact.id: h for h in await memory.held(home, alana)}
            replaced = by_id[coffee].replaced
            assert replaced is not None and (replaced.text, replaced.valid_to) == ("Alana likes tea", LATER)
            assert by_id[rested].replaced is None
            assert tea not in by_id and hidden not in by_id

    run(scenario())


def test_the_source_says_its_kind_start_and_whether_the_person_took_part(db_url: str) -> None:
    home = household(db_url)
    alana, ella = person(db_url, home, "alana"), person(db_url, home, "ella")
    theirs, ours = conversation(db_url, home, "brainstorm"), conversation(db_url, home, "command")
    take_part(db_url, ours, alana)
    take_part(db_url, theirs, ella)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (told_by_ella,) = await memory.apply(home, theirs, [Add(new(alana, ella, "Alana is vegetarian"))], AT)
            (told_by_me,) = await memory.apply(home, ours, [Add(new(alana, alana, "Alana likes tea"))], AT)
            by_id = {h.fact.id: h.source for h in await memory.held(home, alana)}
            assert (by_id[told_by_ella].conversation_id, by_id[told_by_ella].conversation_kind,
                    by_id[told_by_ella].took_part) == (theirs, "brainstorm", False)
            assert (by_id[told_by_me].conversation_kind, by_id[told_by_me].took_part) == ("command", True)
            started = scalar(db_url, "SELECT started_at FROM conversations WHERE id = %s", (ours,))
            assert by_id[told_by_me].started_at == started

    run(scenario())


def test_forget_deletes_the_whole_chain_and_nothing_else_and_logs_only_counts(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    alana = person(db_url, home, "alana")
    talk = conversation(db_url, home)
    logs.setup()

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            first, kept = await memory.apply(home, talk, [Add(new(alana, alana, "Alana likes tea")),
                                                          Add(new(alana, alana, "Alana owns a kiln"))], AT)
            (second,) = await memory.apply(home, talk, [Update(first, new(alana, alana, "Alana likes coffee"))], AT)
            (third,) = await memory.apply(home, talk, [Update(second, new(alana, alana, "Alana likes cocoa"))], LATER)
            capsys.readouterr()
            assert await memory.forget(home, third, by=alana) == 3
            assert scalar(db_url, "SELECT array_agg(id ORDER BY id) FROM facts") == [kept]
            with pytest.raises(ValueError):
                await memory.forget(home, first, by=alana)
            with pytest.raises(ValueError):
                await memory.forget(household(db_url, "away"), kept, by=alana)
            assert scalar(db_url, "SELECT count(*) FROM facts") == 1

    run(scenario())
    out = capsys.readouterr().out
    (line,) = events(out, "memory.forgotten")
    assert (line["household"], line["by"], line["deleted"]) == (str(home), str(alana), "3")
    assert len(events(out, "memory.forget_refused")) == 2
    assert "Alana" not in out and "cocoa" not in out
