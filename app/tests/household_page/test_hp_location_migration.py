"""The household-location migration leaves every existing household with no location, refuses a half or out-of-range
location in the table itself, People reads one back, and downgrading drops the columns."""

from typing import LiteralString

import psycopg
import pytest
from alembic import command
from ashley.db.migrate import alembic_config
from ashley.db.pool import PoolDatabase
from ashley.people.postgres import PostgresPeople
from contract.conversations_support import run, scalar
from test_proposals_migration import revision_named

from test_hp_migration import columns


def test_existing_households_have_no_location(empty_database: str) -> None:
    this, before = revision_named("household_location")
    command.upgrade(alembic_config(empty_database), before)
    home = int(scalar(empty_database, "INSERT INTO households (name, timezone) VALUES ('Willow', 'UTC') RETURNING id"))
    command.upgrade(alembic_config(empty_database), this)
    with psycopg.connect(empty_database) as conn:
        row = conn.execute("SELECT latitude, longitude FROM households WHERE id = %s", (home,)).fetchone()
    assert row == (None, None)


@pytest.mark.parametrize("update", [
    "UPDATE households SET latitude = 51.5 WHERE id = %s", "UPDATE households SET longitude = -0.12 WHERE id = %s",
    "UPDATE households SET latitude = 91, longitude = 0 WHERE id = %s",
    "UPDATE households SET latitude = 0, longitude = 181 WHERE id = %s"])
def test_the_table_refuses_a_half_or_out_of_range_location(db_url: str, update: LiteralString) -> None:
    home = int(scalar(db_url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    with psycopg.connect(db_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(update, (home,))
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE households SET latitude = 51.5, longitude = -0.12 WHERE id = %s", (home,))


def test_people_reads_the_location(db_url: str) -> None:
    home = int(scalar(db_url, "INSERT INTO households (name, latitude, longitude) VALUES ('Willow', 51.5072, -0.1276) "
                              "RETURNING id"))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            found = await PostgresPeople(database).household(home)
        finally:
            await database.close()
        assert found is not None and (found.latitude, found.longitude) == (51.5072, -0.1276)

    run(scenario())


def test_downgrading_drops_the_columns(empty_database: str) -> None:
    this, before = revision_named("household_location")
    command.upgrade(alembic_config(empty_database), this)
    assert {"latitude", "longitude"} <= columns(empty_database)
    command.downgrade(alembic_config(empty_database), before)
    assert not {"latitude", "longitude"} & columns(empty_database)
