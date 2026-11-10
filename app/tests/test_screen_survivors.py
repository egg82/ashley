"""Directed tests for planted mutants the blind suite let live: a closed screen bench stays out of a person's closed list."""

import psycopg
from ashley.workshop.commands import Move
from ashley.workshop.model import HER, Owner, Place
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from screen_bench_support import device, household, person, shop


def test_a_screen_bench_that_is_closed_is_in_no_persons_closed_list(db_url: str) -> None:
    home = household(db_url)
    me = Owner(home, person(db_url, home))
    tablet = device(db_url, home)

    async def scenario() -> None:
        async with shop(db_url) as (workshop, _):
            await workshop.apply_screen(home, tablet, Move(HER, 4, Place(0, "large")))
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("UPDATE benches SET closed_at = now() WHERE device_id = %s", (tablet,))
            assert await workshop.closed_benches(me) == [] and await workshop.open_benches(me) == []

    run(scenario())
