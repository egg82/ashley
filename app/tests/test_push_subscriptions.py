"""Subscriptions over a real database: a browser added for a person is counted and listed for them alone, oldest first;
adding it again for another person moves it with the new keys; removing it needs the person it belongs to; `gone`
forgets it and `delivered` records the time; a person deleted takes their browsers with them; an unreachable database
is SubscriptionsUnavailable."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from ashley.channels.push.postgres_subscriptions import PostgresSubscriptions
from ashley.channels.push.subscriptions import Subscriptions, SubscriptionsUnavailable
from ashley.db.pool import PoolDatabase
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from push_support import AUTH, browser


@asynccontextmanager
async def subscriptions_on(url: str) -> AsyncGenerator[Subscriptions]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresSubscriptions(database)
    finally:
        await database.close()


def test_a_browser_is_counted_and_listed_for_its_person_alone(db_url: str) -> None:
    hid = household(db_url)
    alana, sam = person(db_url, hid, "Alana"), person(db_url, hid, "Sam")

    async def scenario() -> None:
        async with subscriptions_on(db_url) as subs:
            await subs.add(hid, alana, browser(1))
            await subs.add(hid, alana, browser(2))
            assert await subs.count(alana, browser(2).endpoint) == (2, True)
            assert await subs.count(alana) == (2, False)
            assert await subs.count(sam, browser(1).endpoint) == (0, False)
            listed = await subs.of(hid, alana)
            assert [s.browser for s in listed] == [browser(1), browser(2)]
            assert {(s.household_id, s.person_id) for s in listed} == {(hid, alana)}
            assert await subs.of(hid, sam) == ()

    run(scenario())


def test_subscribing_a_browser_again_moves_it_with_its_new_keys(db_url: str) -> None:
    hid = household(db_url)
    alana, sam = person(db_url, hid, "Alana"), person(db_url, hid, "Sam")
    rekeyed = replace(browser(1), auth=AUTH[::-1])

    async def scenario() -> None:
        async with subscriptions_on(db_url) as subs:
            await subs.add(hid, alana, browser(1))
            await subs.add(hid, sam, rekeyed)
            assert await subs.count(alana, browser(1).endpoint) == (0, False)
            assert [s.browser for s in await subs.of(hid, sam)] == [rekeyed]

    run(scenario())


def test_removing_needs_the_person_it_belongs_to(db_url: str) -> None:
    hid = household(db_url)
    alana, sam = person(db_url, hid, "Alana"), person(db_url, hid, "Sam")

    async def scenario() -> None:
        async with subscriptions_on(db_url) as subs:
            await subs.add(hid, alana, browser(1))
            await subs.remove(sam, browser(1).endpoint)
            assert await subs.count(alana) == (1, False)
            await subs.remove(alana, browser(1).endpoint)
            assert await subs.count(alana) == (0, False)

    run(scenario())


def test_gone_forgets_it_and_delivered_records_the_time(db_url: str) -> None:
    hid = household(db_url)
    alana = person(db_url, hid, "Alana")

    async def scenario() -> None:
        async with subscriptions_on(db_url) as subs:
            await subs.add(hid, alana, browser(1))
            await subs.add(hid, alana, browser(2))
            first, second = await subs.of(hid, alana)
            await subs.delivered(second.id)
            await subs.gone(first.id)
            assert [s.id for s in await subs.of(hid, alana)] == [second.id]

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM push_subscriptions WHERE last_success_at IS NOT NULL") == 1


def test_a_person_deleted_takes_their_browsers(db_url: str) -> None:
    hid = household(db_url)
    alana = person(db_url, hid, "Alana")

    async def scenario() -> None:
        async with subscriptions_on(db_url) as subs:
            await subs.add(hid, alana, browser(1))

    run(scenario())
    scalar(db_url, "DELETE FROM people WHERE id = %s RETURNING id", (alana,))
    assert scalar(db_url, "SELECT count(*) FROM push_subscriptions") == 0


def test_an_unreachable_database_is_unavailable() -> None:
    async def scenario() -> None:
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.3)
        await database.open()
        try:
            subs = PostgresSubscriptions(database)
            with pytest.raises(SubscriptionsUnavailable):
                await subs.count(1)
            with pytest.raises(SubscriptionsUnavailable):
                await subs.add(1, 1, browser(1))
        finally:
            await database.close()

    run(scenario())
