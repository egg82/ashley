"""`Later` through `PostgresWatches.record`: only `next_check_at` moves, `retry_s` on, for an armed and a paused watch."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ashley.watches.config import CONFIG
from ashley.watches.model import Failed, Later, Quiet
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run
from test_watches_postgres import ITEMS, arm_for, store


def test_later_moves_only_the_next_check_and_leaves_failures_state_and_baseline(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url, replace(CONFIG, fail_after=2, retry_s=300)) as w:
            a = await w.arm(arm_for(home, who, baseline=ITEMS, interval_s=5))
            assert await w.record(a.id, 0, Failed("unreachable"))
            assert await w.record(a.id, 0, Later())
            got = await w.get(a.id)
            assert got is not None and (got.state, got.failures, got.version, got.baseline) == ("armed", 1, 0, ITEMS)
            assert datetime.now(UTC) + timedelta(seconds=200) < got.next_check_at
            assert await w.due(10) == ()
            assert await w.record(a.id, 0, Failed("refused"))
            assert await w.record(a.id, 0, Later())
            paused = await w.get(a.id)
            assert paused is not None and (paused.state, paused.failures, paused.reason) == ("paused", 2, "refused")
            assert await w.record(a.id, 0, Quiet(False))
    run(go())
