"""A watch's `brief` and `standing` through `PostgresWatches`: stored and read back, replaced by arming again,
and a standing watch's expiry moving on each successful read and on nothing else."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashley.criteria.condition import Condition
from ashley.criteria.items import ItemPredicate
from ashley.db.pool import PoolDatabase
from ashley.watches.model import Arm, Baseline, Failed, Later, Quiet, Woke
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar
from typing import Any

WHEN: Condition = ((ItemPredicate("changed", field="seq"),),)
ITEMS = {"s1": {"status": "working", "seq": 1}}
HOURS = 7200.0


def arm_for(home: int, who: int, **over: object) -> Arm:
    base = Arm(home, who, "claude_session", "s1", "the build", None, "ashley", ("status", "seq"), WHEN, None, None, 15,
               datetime.now(UTC) + timedelta(seconds=HOURS))
    return replace(base, **over)


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[Watches]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresWatches(db)
    finally:
        await db.close()


def result[T](scenario: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(scenario, 25.0))


def left(db_url: str, watch_id: int) -> float:
    return float(scalar(db_url, f"SELECT extract(epoch FROM expires_at - now()) FROM watches WHERE id = {watch_id}"))


def soon(db_url: str, watch_id: int) -> None:
    scalar(db_url, f"WITH u AS (UPDATE watches SET expires_at = now() + interval '1 minute' WHERE id = {watch_id} "
                   "RETURNING 1) SELECT count(*) FROM u")


def test_brief_and_standing_are_stored_and_read_back(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            made = await w.arm(arm_for(home, who, brief="sort my mail", standing=True))
            got = await w.get(made.id)
            assert got is not None
            assert (got.brief, got.standing) == ("sort my mail", True)
            plain = await w.arm(arm_for(home, who, target="s2"))
            other = await w.get(plain.id)
            assert other is not None and (other.brief, other.standing) == (None, False)
    run(go())


def test_arming_again_replaces_brief_and_standing(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            first = await w.arm(arm_for(home, who, brief="a", standing=True))
            again = await w.arm(arm_for(home, who, brief="b", standing=False))
            assert (again.id, again.new) == (first.id, False)
            got = await w.get(first.id)
            assert got is not None and (got.brief, got.standing) == ("b", False)
            await w.arm(arm_for(home, who))
            bare = await w.get(first.id)
            assert bare is not None and (bare.brief, bare.standing) == (None, False)
    run(go())


@pytest.mark.parametrize("over", [{"brief": ""}, {"brief": "x" * 501}, {"brief": "a\x00b"}])
def test_arm_refuses_a_bad_brief_before_writing(db_url: str, over: dict[str, object]) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            with pytest.raises(ValueError):
                await w.arm(arm_for(home, who, **over))
    run(go())
    assert scalar(db_url, "SELECT count(*) FROM watches") == 0


@pytest.mark.parametrize("check", [Baseline(ITEMS), Quiet(False), Woke(ITEMS, (), False)])
def test_a_successful_read_moves_a_standing_watchs_expiry_forward_by_the_time_it_was_armed_for(
        db_url: str, check: Baseline | Quiet | Woke) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> int:
        async with store(db_url) as w:
            made = await w.arm(arm_for(home, who, standing=True, baseline=ITEMS))
            soon(db_url, made.id)
            assert left(db_url, made.id) < 120
            assert await w.record(made.id, 0, check)
            return made.id
    watch_id = result(go())
    assert HOURS - 60 < left(db_url, watch_id) <= HOURS


def test_a_failed_or_later_read_leaves_a_standing_watchs_expiry_and_it_ends_when_the_source_keeps_failing(
        db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> int:
        async with store(db_url) as w:
            made = await w.arm(arm_for(home, who, standing=True, baseline=ITEMS))
            soon(db_url, made.id)
            assert await w.record(made.id, 0, Failed("unreachable"))
            assert await w.record(made.id, 0, Later())
            assert left(db_url, made.id) < 120
            scalar(db_url, f"WITH u AS (UPDATE watches SET expires_at = now() - interval '1 second' "
                           f"WHERE id = {made.id} RETURNING 1) SELECT count(*) FROM u")
            assert (await w.expire(3600.0)).expired == 1
            return made.id
    watch_id = result(go())
    assert scalar(db_url, f"SELECT reason FROM watches WHERE id = {watch_id}") == "expired"


def test_a_watch_that_is_not_standing_keeps_its_expiry_through_reads(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> int:
        async with store(db_url) as w:
            made = await w.arm(arm_for(home, who, baseline=ITEMS))
            soon(db_url, made.id)
            assert await w.record(made.id, 0, Quiet(False))
            return made.id
    assert left(db_url, result(go())) < 120


def test_a_standing_watch_ends_only_when_disarmed_or_until_holds_never_by_a_read(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> bool:
        async with store(db_url) as w:
            made = await w.arm(arm_for(home, who, standing=True, baseline=ITEMS))
            assert await w.record(made.id, 0, Quiet(False))
            assert (await w.expire(3600.0)).expired == 0
            return await w.disarm(home, who, "claude_session", "s1")
    assert result(go())
    assert scalar(db_url, "SELECT reason FROM watches") == "disarmed"
