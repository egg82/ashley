"""What the session sense's store tests held that the watches store owes too: a watch goes with its person, and an
unreachable database raises the service's own error."""

from datetime import UTC, datetime, timedelta

import pytest
from ashley.criteria.condition import Condition
from ashley.criteria.items import ItemPredicate
from ashley.db.pool import PoolDatabase
from ashley.watches.model import Arm
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import WatchesUnavailable
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar

WHEN: Condition = ((ItemPredicate("changed", field="seq"),),)


def arm_for(home: int, who: int) -> Arm:
    return Arm(home, who, "claude_session", "s1", "the build", None, "handoff", ("status", "seq"), WHEN, None, None, 15,
               datetime.now(UTC) + timedelta(hours=1))


def test_a_watch_goes_with_its_person(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def go() -> None:
        db = PoolDatabase(db_url, connect_timeout_s=5.0)
        await db.open()
        try:
            store = PostgresWatches(db)
            await store.arm(arm_for(home, alana))
            scalar(db_url, "WITH d AS (DELETE FROM people WHERE id = %s RETURNING 1) SELECT count(*) FROM d", (alana,))
            assert await store.live(home, alana) == () and scalar(db_url, "SELECT count(*) FROM watches") == 0
        finally:
            await db.close()
    run(go())


def test_an_unreachable_database_raises_the_services_own_error() -> None:
    async def go() -> None:
        db = PoolDatabase(unreachable_conninfo(), connect_timeout_s=0.1)
        with pytest.raises(WatchesUnavailable):
            await PostgresWatches(db).live(1, 1)
    run(go())
