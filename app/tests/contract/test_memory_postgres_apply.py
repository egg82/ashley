"""Directed tests for PostgresMemory.apply, its failures and its log lines, against a migrated database."""

from datetime import UTC, datetime

import pytest
from ashley import logs
from ashley import services
from ashley.db.database import Database
from ashley.memory.memory import Memory, MemoryUnavailable
from ashley.memory.model import Add, Asker, Forget, Invalidate, Kind, NewFact, Noop, Update, Visibility
from ashley.memory.postgres import PostgresMemory
from ashley.settings import Settings
from ashley.wiring import wire

from contract_support import unreachable_conninfo
from conversations_support import events, household, person, run, scalar
from memory_support import conversation, pool

AT = datetime(2026, 3, 1, tzinfo=UTC)


def fact(owner: int | None, text: str = "Alana likes tea", kind: Kind = "preference", visibility: Visibility = "shared",
         stated: bool = False) -> NewFact:
    return NewFact(owner, owner, visibility, stated, kind, False, text)


def stored(url: str) -> str:
    """Every fact row, so a refused call can be shown to have changed nothing."""
    return str(scalar(url, "SELECT coalesce(string_agg(f::text, '|' ORDER BY id), '') FROM facts f"))


def column(url: str, fact_id: int, name: str) -> object:
    return scalar(url, f"SELECT {name} FROM facts WHERE id = %s", (fact_id,))


def scene(url: str) -> tuple[int, int, int]:
    """A household, a person in it and a conversation in it."""
    home = household(url)
    return home, person(url, home, "alana"), conversation(url, home)


def test_update_closes_its_target_and_returns_inserted_ids_in_op_order(db_url: str) -> None:
    home, alana, talk = scene(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (old,) = await memory.apply(home, talk, [Add(fact(alana, "Alana likes tea"))], AT)
            first, second = await memory.apply(home, talk, [
                Noop(None), Update(old, fact(alana, "Alana likes coffee")), Add(fact(alana, "Alana owns a kiln"))], AT)
            assert first < second
            assert (column(db_url, old, "valid_to"), column(db_url, old, "superseded_by")) == (AT, first)
            assert column(db_url, first, "valid_to") is None
            assert column(db_url, first, "source_conversation_id") == talk

    run(scenario())


@pytest.mark.parametrize("bad", ["missing", "closed", "other household"])
def test_a_target_that_is_not_current_in_the_household_applies_nothing(db_url: str, bad: str) -> None:
    home, alana, talk = scene(db_url)
    away = household(db_url, "away")
    away_talk = conversation(db_url, away)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (mine,) = await memory.apply(home, talk, [Add(fact(alana))], AT)
            (theirs,) = await memory.apply(away, away_talk, [Add(fact(None, "Biscuit is fed at 6am", "home"))], AT)
            (closed,) = await memory.apply(home, talk, [Add(fact(alana, "Alana has pottery"))], AT)
            await memory.apply(home, talk, [Invalidate(closed)], AT)
            target = {"missing": theirs + 100, "closed": closed, "other household": theirs}[bad]
            before = stored(db_url)
            for op in (Update(target, fact(alana, "new")), Invalidate(target), Forget(target)):
                with pytest.raises(ValueError):
                    await memory.apply(home, talk, [Add(fact(alana, "first")), Invalidate(mine), op], AT)
            assert stored(db_url) == before

    run(scenario())


def test_a_fact_naming_another_households_person_applies_nothing(db_url: str) -> None:
    home, alana, talk = scene(db_url)
    stranger = person(db_url, household(db_url, "away"), "stranger")

    async def scenario() -> None:
        async with pool(db_url) as db:
            with pytest.raises(ValueError):
                await PostgresMemory(db).apply(home, talk, [Add(fact(alana)), Add(fact(stranger))], AT)
        assert stored(db_url) == ""

    run(scenario())


@pytest.mark.parametrize(("kind", "stated", "kept"), [
    ("health", False, "private"), ("health", True, "shared"), ("preference", False, "shared")])
def test_health_is_pinned_private_unless_its_visibility_was_stated(db_url: str, kind: Kind, stated: bool,
                                                                    kept: str) -> None:
    home, alana, talk = scene(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            (made,) = await PostgresMemory(db).apply(home, talk, [Add(fact(alana, "x", kind, "shared", stated))], AT)
        assert (column(db_url, made, "visibility"), column(db_url, made, "visibility_stated")) == (kept, stated)

    run(scenario())


@pytest.mark.parametrize("kind", ["home", "health"])
def test_a_household_fact_is_stored_shared_whatever_it_was_marked(db_url: str, kind: Kind) -> None:
    home, _, talk = scene(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            (made,) = await PostgresMemory(db).apply(home, talk, [Add(fact(None, "Mochi has a vet visit", kind,
                                                                           "private"))], AT)
        assert column(db_url, made, "visibility") == "shared"

    run(scenario())


def test_forget_deletes_the_target_and_every_fact_it_superseded(db_url: str) -> None:
    home, alana, talk = scene(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (kept,) = await memory.apply(home, talk, [Add(fact(alana, "Alana owns a kiln"))], AT)
            (first,) = await memory.apply(home, talk, [Add(fact(alana, "tea"))], AT)
            (second,) = await memory.apply(home, talk, [Update(first, fact(alana, "coffee"))], AT)
            (third,) = await memory.apply(home, talk, [Update(second, fact(alana, "water"))], AT)
            with pytest.raises(ValueError):
                await memory.apply(home, talk, [Forget(second)], AT)
            assert await memory.apply(home, talk, [Forget(third)], AT) == ()
            assert scalar(db_url, "SELECT array_agg(id) FROM facts") == [kept]

    run(scenario())


def test_an_unreachable_database_is_memory_unavailable() -> None:
    async def scenario() -> None:
        async with pool(unreachable_conninfo(), connect_timeout_s=0.1) as db:
            memory = PostgresMemory(db)
            with pytest.raises(MemoryUnavailable):
                await memory.recall(Asker(1, None, False, AT), "tea")
            with pytest.raises(MemoryUnavailable):
                await memory.apply(1, 1, [Add(fact(None))], AT)

    run(scenario())


def test_log_lines_carry_ids_and_counts_never_text_or_query(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home, alana, talk = scene(db_url)
    planted_text, planted_query = "Alana hides zqxplanted", "where zqxplanted"
    logs.setup({"LOG_LEVEL": "info"})

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (made,) = await memory.apply(home, talk, [Add(fact(alana, planted_text)), Noop(None)], AT)
            assert [r.fact.id for r in await memory.recall(Asker(home, alana, True, AT), planted_query)] == [made]
            with pytest.raises(ValueError):
                await memory.apply(home, talk, [Invalidate(made + 1)], AT)
            out = capsys.readouterr().out
            assert "zqxplanted" not in out
            assert [(e["conversation"], e["add"], e["noop"], e["update"], e["inserted"])
                    for e in events(out, "memory.apply")] == [(str(talk), "1", "1", "0", str(made))]
            assert [(e["household"], e["returned"], e["facts"]) for e in events(out, "memory.recall")] == [
                (str(home), "1", str(made))]
            assert [(e["reason"], e["target"]) for e in events(out, "memory.apply_refused")] == [
                ("not_current", str(made + 1))]

    run(scenario())


def test_wiring_answers_a_postgres_memory_over_the_wired_database(db_url: str) -> None:
    home, alana, talk = scene(db_url)
    wire(Settings(database_url=db_url, build_version="test"))

    async def scenario() -> None:
        db = services.get(Database)
        await db.open()
        try:
            memory = services.get(Memory)
            assert isinstance(memory, PostgresMemory)
            (made,) = await memory.apply(home, talk, [Add(fact(alana))], AT)
            assert [r.fact.id for r in await memory.recall(Asker(home, None, False, AT), "tea")] == [made]
        finally:
            await db.close()

    try:
        run(scenario())
    finally:
        services.unregister(Memory)
