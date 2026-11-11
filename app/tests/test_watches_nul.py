"""A watch's reads are outside text, and a NUL (U+0000) in one reaches neither the baseline column nor the `wakes`
jsonb a change is stored in: the read is cleaned where it becomes items."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from ashley.criteria.condition import Condition
from ashley.criteria.items import ItemPredicate
from ashley.db.pool import PoolDatabase
from ashley.mail.model import Header
from ashley.watches import judge
from ashley.watches.mail_inbox import items_of
from ashley.watches.model import Arm, Baseline, Woke
from ashley.watches.postgres import PostgresWatches
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar

WHEN: Condition = ((ItemPredicate("changed", field="subject"),),)
SEEN = datetime(2026, 11, 10, tzinfo=UTC)


def header(subject: str) -> Header:
    return Header("m1", "a@example.test", "b@example.test", subject, SEEN, "", (), "inbox", True, 0)


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[PostgresWatches]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresWatches(db)
    finally:
        await db.close()


def armed(home: int, who: int) -> Arm:
    return Arm(home, who, "mail_inbox", "me@example.test", "inbox", None, "ashley", ("from", "subject"), WHEN, None,
               None, 15, datetime.now(UTC) + timedelta(hours=1))


def test_a_read_with_a_nul_is_stored_in_the_baseline_and_the_wake_without_it(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as watches:
            made = await watches.arm(armed(home, who))
            assert await watches.record(made.id, 0, Baseline(items_of([header("plan\x00 A")])))
            watch = await watches.get(made.id)
            assert watch is not None and watch.baseline is not None
            check = judge.judge(items_of([header("plan\x00 B")]), watch)
            assert isinstance(check, Woke)
            assert await watches.record(made.id, watch.version, check)

    run(go())
    assert scalar(db_url, "SELECT baseline->'m1'->>'subject' FROM watches") == "plan B"
    assert scalar(db_url, "SELECT changes->'items'->0->'after'->>'subject' FROM wakes") == "plan B"
    assert scalar(db_url, "SELECT changes->'items'->0->'before'->>'subject' FROM wakes") == "plan A"
