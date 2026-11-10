"""A household's model choices on a real database: a write replaces or clears one task's choice, each household reads
only its own, a conversation names its household, a household gone takes its choices with it, and a database out of
reach is RoutesUnavailable."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import psycopg
import pytest
from ashley.db.database import NullDatabase
from ashley.db.pool import PoolDatabase
from ashley.inference.postgres_route_choice_write import PostgresRouteChoiceWriter
from ashley.inference.postgres_route_choices import PostgresRouteChoices
from ashley.inference.route_choices import Choice, RoutesUnavailable
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from household_routes_support import events

OPUS, SONNET = Choice("anthropic", "claude-opus-5-5"), Choice("anthropic", "claude-sonnet-5-5")


def homes(url: str) -> tuple[int, int, int, int]:
    """Two households, a person in each."""
    with psycopg.connect(url) as conn:
        one, two = admin.add_household(conn, "one", "UTC"), admin.add_household(conn, "two", "UTC")
        return one, admin.add_person(conn, one, "Alana"), two, admin.add_person(conn, two, "Kim")


def on[R](url: str, work: Callable[[PostgresRouteChoices, PostgresRouteChoiceWriter], Awaitable[R]]) -> R:
    async def scenario() -> R:
        database = PoolDatabase(url)
        await database.open()
        try:
            return await asyncio.wait_for(work(PostgresRouteChoices(database), PostgresRouteChoiceWriter(database)), 25)
        finally:
            await database.close()
    return asyncio.run(scenario())


def test_a_choice_is_stored_replaced_and_cleared_per_task(db_url: str) -> None:
    one, alana, two, kim = homes(db_url)

    async def work(reads: PostgresRouteChoices, writer: PostgresRouteChoiceWriter) -> list[object]:
        await writer.put(one, alana, "chat", OPUS)
        await writer.put(one, alana, "brainstorm", OPUS)
        await writer.put(two, kim, "chat", SONNET)
        first = await reads.all()
        await writer.put(one, alana, "chat", SONNET)
        await writer.put(one, alana, "brainstorm", None)
        await writer.put(one, alana, "command", None)
        return [first, await reads.all(), await reads.of_household(one), await reads.of_household(99)]
    first, then, own, none = on(db_url, work)
    assert first == {one: {"chat": OPUS, "brainstorm": OPUS}, two: {"chat": SONNET}}
    assert then == {one: {"chat": SONNET}, two: {"chat": SONNET}}
    assert own == {"chat": SONNET} and none == {}
    assert scalar(db_url, "SELECT person_id FROM household_routes WHERE household_id = %s", (one,)) == alana


def test_the_write_is_logged_with_ids_and_the_model(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    one, alana, _, _ = homes(db_url)
    on(db_url, lambda _, w: w.put(one, alana, "chat", OPUS))
    on(db_url, lambda _, w: w.put(one, alana, "chat", None))
    assert events(caplog, "inference.choice_set") == [
        {"household": one, "person": alana, "task": "chat", "outcome": "set", "provider": "anthropic",
         "model": "claude-opus-5-5"},
        {"household": one, "person": alana, "task": "chat", "outcome": "cleared"}]


def test_a_conversation_names_its_household(db_url: str) -> None:
    one, _, _, _ = homes(db_url)
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (one,)))
    assert on(db_url, lambda r, _: r.household_of(conversation)) == one
    assert on(db_url, lambda r, _: r.household_of(conversation + 1000)) is None


def test_a_household_gone_takes_its_choices_and_a_person_gone_leaves_them(db_url: str) -> None:
    one, alana, two, kim = homes(db_url)
    on(db_url, lambda _, w: w.put(one, alana, "chat", OPUS))
    on(db_url, lambda _, w: w.put(two, kim, "chat", OPUS))
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("DELETE FROM people WHERE id = %s", (kim,))
        conn.execute("DELETE FROM people WHERE household_id = %s", (one,))
        conn.execute("DELETE FROM households WHERE id = %s", (one,))
    assert on(db_url, lambda r, _: r.all()) == {two: {"chat": OPUS}}


def test_a_task_the_code_no_longer_knows_is_left_out(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO household_routes (household_id, task, provider, model, person_id) "
                     "VALUES (%s, 'shout', 'anthropic', 'm', %s)", (one, alana))
    assert on(db_url, lambda r, _: r.all()) == {}


def test_a_database_out_of_reach_is_routes_unavailable() -> None:
    database = NullDatabase()

    async def scenario() -> None:
        for call in (PostgresRouteChoices(database).all(), PostgresRouteChoices(database).of_household(1),
                     PostgresRouteChoices(database).household_of(1),
                     PostgresRouteChoiceWriter(database).put(1, 1, "chat", OPUS)):
            with pytest.raises(RoutesUnavailable):
                await call
    asyncio.run(asyncio.wait_for(scenario(), 25))
