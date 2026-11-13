"""The wakes Home Assistant sends, over a real database: one event id is one wake per household however often it
arrives (a retry, both sites), due until settled, settled once, and a settled wake past its keeping is pruned while
an unsettled one never is."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Wake, Wakes, WakesUnavailable
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import run, scalar

AT = datetime(2026, 10, 31, 18, 2, tzinfo=UTC)


def device(url: str, home: int, n: int = 1) -> int:
    return int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                           "VALUES (%s, 'house', 'house', 'household', 'text', 'chat', decode(%s, 'hex')) RETURNING id",
                      (home, f"{n:064x}")))


def wake(home: int, event_id: str = "ctx-1", event: str = "alana_arrived") -> Wake:
    return Wake(home, event_id, event, "person.alana", None, AT)


@asynccontextmanager
async def store(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[Wakes]:
    db = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await db.open()
    try:
        yield PostgresWakes(db)
    finally:
        await db.close()


def test_one_event_id_is_one_wake_however_often_it_arrives(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    async def scenario() -> None:
        async with store(db_url) as wakes:
            first = await wakes.receive(device(db_url, home), wake(home))
            again = await wakes.receive(device(db_url, home, 2), wake(home, event="garage_open"))
            elsewhere = await wakes.receive(device(db_url, other, 3), wake(other))
            assert first.new and not again.new and again.id == first.id
            assert elsewhere.new and elsewhere.id != first.id
            due = await wakes.due(10)
            assert [d.id for d in due] == [first.id, elsewhere.id]
            assert due[0].wake == wake(home)
    run(scenario())


def test_a_wake_is_due_until_settled_and_settled_once(db_url: str) -> None:
    home = household(db_url)
    async def scenario() -> None:
        async with store(db_url) as wakes:
            made = device(db_url, home)
            one, two = [(await wakes.receive(made, wake(home, f"ctx-{n}"))).id for n in (1, 2)]
            assert [d.id for d in await wakes.due(1)] == [one]
            assert await wakes.settle(one, "turn")
            assert not await wakes.settle(one, "no_rule")
            assert [d.id for d in await wakes.due(10)] == [two]
            assert scalar(db_url, "SELECT outcome FROM wakes WHERE id = %s", (one,)) == "turn"
    run(scenario())


def test_a_settled_wake_past_its_keeping_is_pruned_and_an_unsettled_one_never_is(db_url: str) -> None:
    home = household(db_url)
    async def scenario() -> None:
        async with store(db_url) as wakes:
            made = device(db_url, home)
            old, young, waiting = [(await wakes.receive(made, wake(home, f"ctx-{n}"))).id for n in (1, 2, 3)]
            for wake_id in (old, young):
                await wakes.settle(wake_id, "turn")
            scalar(db_url, "WITH u AS (UPDATE wakes SET received_at = received_at - interval '2 days', "
                           "settled_at = settled_at - interval '2 days' WHERE id IN (%s, %s) RETURNING 1) "
                           "SELECT count(*) FROM u", (old, waiting))
            assert await wakes.prune(86400) == 1
            left = scalar(db_url, "SELECT array_agg(id ORDER BY id) FROM wakes")
            assert left == [young, waiting]
    run(scenario())


def test_an_unreachable_database_is_wakes_unavailable() -> None:
    async def scenario() -> None:
        async with store(unreachable_conninfo(), connect_timeout_s=0.1) as wakes:
            for call in (wakes.receive(1, wake(1)), wakes.due(1), wakes.settle(1, "turn"), wakes.prune(1)):
                with pytest.raises(WakesUnavailable):
                    await call
    run(scenario())


def test_an_unwired_process_raises_wakes_unavailable() -> None:
    async def scenario() -> None:
        with pytest.raises(WakesUnavailable):
            await Wakes.null().receive(1, wake(1))
        with pytest.raises(WakesUnavailable):
            await Wakes.null().due(1)
    run(scenario())
