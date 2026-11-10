"""The household-locale migration gives every existing household what the code assumed before: `en-US`, imperial units
and a 24-hour clock; People reads them back; and downgrading drops the columns."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from ashley.db.pool import PoolDatabase
from ashley.people.postgres import PostgresPeople
from contract.conversations_support import run, scalar
from test_proposals_migration import revision_named


def columns(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'households'").fetchall()
    return {r[0] for r in rows}


def test_existing_households_keep_what_the_code_assumed(empty_database: str) -> None:
    this, before = revision_named("household_locale")
    command.upgrade(alembic_config(empty_database), before)
    home = int(scalar(empty_database, "INSERT INTO households (name, timezone) VALUES ('Willow', 'America/Denver') "
                                      "RETURNING id"))
    command.upgrade(alembic_config(empty_database), this)
    with psycopg.connect(empty_database) as conn:
        row = conn.execute("SELECT locale, unit_system, clock FROM households WHERE id = %s", (home,)).fetchone()
    assert row == ("en-US", "imperial", "24h")


def test_people_reads_the_new_fields(db_url: str) -> None:
    home = int(scalar(db_url, "INSERT INTO households (name, timezone, locale, unit_system, clock) "
                              "VALUES ('Willow', 'Europe/London', 'en-GB', 'metric', '12h') RETURNING id"))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            found = await PostgresPeople(database).household(home)
        finally:
            await database.close()
        assert found is not None
        assert (found.locale, found.unit_system, found.clock) == ("en-GB", "metric", "12h")

    run(scenario())


def test_downgrading_drops_the_columns(empty_database: str) -> None:
    this, before = revision_named("household_locale")
    command.upgrade(alembic_config(empty_database), this)
    assert {"locale", "unit_system", "clock"} <= columns(empty_database)
    command.downgrade(alembic_config(empty_database), before)
    assert not {"locale", "unit_system", "clock"} & columns(empty_database)
