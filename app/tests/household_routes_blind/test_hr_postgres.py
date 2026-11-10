"""Pins the Postgres implementations of the choice store (`postgres_route_choices`, `postgres_route_choice_write`;
table `household_routes`) against a migrated database: what `put` stores `all`, `of_household` and `household_of` read
back, per household, replacing and clearing; the write is logged as `inference.choice_set` with ids and nothing else."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from ashley.db.pool import PoolDatabase
from ashley.inference.postgres_route_choice_write import PostgresRouteChoiceWriter
from ashley.inference.postgres_route_choices import PostgresRouteChoices
from ashley.inference.route_choices import Choice
from contract.conversations_support import household, person, run, scalar
from household_routes_blind_support import events


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[tuple[PostgresRouteChoices, PostgresRouteChoiceWriter]]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresRouteChoices(db), PostgresRouteChoiceWriter(db)
    finally:
        await db.close()


def conversation(url: str, household_id: int) -> int:
    return int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                      (household_id,)))


def test_a_household_that_chose_nothing_is_absent_and_reads_empty(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with store(db_url) as (reads, _):
            assert dict(await reads.all()) == {} and dict(await reads.of_household(home)) == {}
    run(scenario())


def test_a_put_is_read_back_by_household_and_task(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with store(db_url) as (reads, writer):
            await writer.put(home, who, "chat", Choice("anthropic", "claude-sonnet-5-5"))
            await writer.put(home, who, "wrap_up", Choice("gemini", "gemini-3.8-flash"))
            assert dict(await reads.of_household(home)) == {"chat": Choice("anthropic", "claude-sonnet-5-5"),
                                                            "wrap_up": Choice("gemini", "gemini-3.8-flash")}
            assert {h: dict(c) for h, c in (await reads.all()).items()} == {home: dict(await reads.of_household(home))}
    run(scenario())


def test_a_put_replaces_the_households_choice_for_that_task_only(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with store(db_url) as (reads, writer):
            await writer.put(home, who, "chat", Choice("a", "m1"))
            await writer.put(home, who, "brainstorm", Choice("c", "m3"))
            await writer.put(home, who, "chat", Choice("b", "m2"))
            assert dict(await reads.of_household(home)) == {"chat": Choice("b", "m2"), "brainstorm": Choice("c", "m3")}
    run(scenario())


def test_a_none_clears_the_choice_and_a_household_with_none_left_is_absent(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with store(db_url) as (reads, writer):
            await writer.put(home, who, "chat", Choice("a", "m1"))
            await writer.put(home, who, "chat", None)
            assert dict(await reads.of_household(home)) == {} and dict(await reads.all()) == {}
            await writer.put(home, who, "wrap_up", None)
    run(scenario())


def test_households_never_read_one_anothers_choices(db_url: str) -> None:
    mine, theirs = household(db_url, "mine"), household(db_url, "theirs")
    me, them = person(db_url, mine), person(db_url, theirs)

    async def scenario() -> None:
        async with store(db_url) as (reads, writer):
            await writer.put(mine, me, "chat", Choice("a", "m1"))
            await writer.put(theirs, them, "chat", Choice("b", "m2"))
            await writer.put(theirs, them, "wrap_up", Choice("c", "m3"))
            assert dict(await reads.of_household(mine)) == {"chat": Choice("a", "m1")}
            await writer.put(theirs, them, "chat", None)
            assert dict(await reads.of_household(mine)) == {"chat": Choice("a", "m1")}
            assert {h: dict(c) for h, c in (await reads.all()).items()} == {
                mine: {"chat": Choice("a", "m1")}, theirs: {"wrap_up": Choice("c", "m3")}}
    run(scenario())


def test_a_choice_outlives_the_connections_that_wrote_it(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def write() -> None:
        async with store(db_url) as (_, writer):
            await writer.put(home, who, "chat", Choice("a", "m1"))

    async def read() -> None:
        async with store(db_url) as (reads, _):
            assert dict(await reads.of_household(home)) == {"chat": Choice("a", "m1")}
    run(write())
    run(read())


def test_a_conversations_household_is_the_one_it_belongs_to_and_an_unknown_one_is_none(db_url: str) -> None:
    mine, theirs = household(db_url, "mine"), household(db_url, "theirs")
    c1, c2 = conversation(db_url, mine), conversation(db_url, theirs)

    async def scenario() -> None:
        async with store(db_url) as (reads, _):
            assert await reads.household_of(c1) == mine and await reads.household_of(c2) == theirs
            assert await reads.household_of(max(c1, c2) + 1000) is None
    run(scenario())


def test_the_person_who_set_a_choice_is_recorded_with_it(db_url: str) -> None:
    home = household(db_url)
    sam, kim = person(db_url, home, "sam"), person(db_url, home, "kim")

    async def scenario() -> None:
        async with store(db_url) as (_, writer):
            await writer.put(home, sam, "chat", Choice("a", "m1"))
            await writer.put(home, kim, "chat", Choice("b", "m2"))
    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM household_routes") == 1
    row: dict[str, Any] = json.loads(scalar(db_url, "SELECT row_to_json(t)::text FROM household_routes t"))
    assert kim in row.values() and home in row.values() and "m2" in row.values()


def test_a_write_is_logged_with_ids_and_the_choice_never_a_key(db_url: str,
                                                              info_logs: pytest.LogCaptureFixture) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with store(db_url) as (_, writer):
            await writer.put(home, who, "chat", Choice("a", "m1"))
            await writer.put(home, who, "chat", None)
    run(scenario())
    set_, cleared = events(info_logs, "inference.choice_set")
    for line in (set_, cleared):
        assert line["household"] == home and line["person"] == who and line["task"] == "chat"
    assert "m1" in str(set_.values()) and "cleared" in (str(cleared.values()) + str(cleared.keys()))
