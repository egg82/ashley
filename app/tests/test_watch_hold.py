"""A person's pause of a watch through `PostgresWatches`: a held watch is not due, takes no check and does not expire, and
releasing it makes it due at once with its expiry moved on by the time it was held; only its own person can hold or
release it."""

from datetime import UTC, datetime, timedelta

from ashley.watches.model import Baseline, Quiet
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar
from test_watches_postgres import ITEMS, arm_for, store


def test_a_held_watch_is_not_due_takes_no_check_and_does_not_expire(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            armed = await w.arm(arm_for(home, who, expires_at=datetime.now(UTC) + timedelta(hours=1)))
            assert [x.id for x in await w.due(10)] == [armed.id]
            assert await w.hold(home, who, armed.id)
            assert await w.due(10) == ()
            assert not await w.record(armed.id, 0, Baseline(ITEMS))
            scalar(db_url, "UPDATE watches SET expires_at = now() - interval '1 minute' WHERE id = %s RETURNING id", (armed.id,))
            assert (await w.expire(3600)).expired == 0
            held = await w.get(armed.id)
            assert held is not None and held.state == "armed" and held.held_at is not None

    run(go())


def test_release_makes_it_due_at_once_and_moves_its_expiry_on_by_the_time_held(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            armed = await w.arm(arm_for(home, who))
            scalar(db_url, "UPDATE watches SET next_check_at = now() + interval '1 hour' WHERE id = %s RETURNING id", (armed.id,))
            assert await w.hold(home, who, armed.id)
            scalar(db_url, "UPDATE watches SET held_at = now() - interval '30 minutes' WHERE id = %s RETURNING id", (armed.id,))
            before = await w.get(armed.id)
            assert before is not None
            assert await w.release(home, who, armed.id)
            after = await w.get(armed.id)
            assert after is not None and after.held_at is None
            assert timedelta(minutes=29) < after.expires_at - before.expires_at < timedelta(minutes=31)
            assert [x.id for x in await w.due(10)] == [armed.id]
            assert await w.record(armed.id, 0, Quiet(False))

    run(go())


def test_holding_twice_keeps_the_first_moment_and_releasing_a_running_watch_changes_nothing(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            armed = await w.arm(arm_for(home, who))
            before = await w.get(armed.id)
            assert await w.release(home, who, armed.id)
            assert await w.get(armed.id) == before
            assert await w.hold(home, who, armed.id)
            first = await w.get(armed.id)
            assert await w.hold(home, who, armed.id)
            again = await w.get(armed.id)
            assert first is not None and again is not None and first.held_at == again.held_at

    run(go())


def test_nobody_holds_or_releases_a_watch_that_is_not_theirs_or_is_over(db_url: str) -> None:
    home = household(db_url)
    mine, other = person(db_url, home), person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            armed = await w.arm(arm_for(home, mine))
            assert not await w.hold(home, other, armed.id)
            assert not await w.hold(home + 1, mine, armed.id)
            assert await w.hold(home, mine, armed.id)
            assert not await w.release(home, other, armed.id)
            held = await w.get(armed.id)
            assert held is not None and held.held_at is not None
            assert await w.disarm(home, mine, "claude_session", "s1")
            assert not await w.hold(home, mine, armed.id)
            assert not await w.release(home, mine, armed.id)

    run(go())
