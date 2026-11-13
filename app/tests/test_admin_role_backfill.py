"""The migration that adds the admin flag, found by its name so a renumber changes nothing: on a deployment that already
has people, every person of the first household becomes an admin, read back from the table, and no one else
does; downgrading takes the flag away."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar
from test_proposals_migration import revision_named


def seed(url: str) -> dict[str, int]:
    first = int(scalar(url, "INSERT INTO households (name) VALUES ('first') RETURNING id"))
    other = int(scalar(url, "INSERT INTO households (name) VALUES ('other') RETURNING id"))
    assert first == 1
    made: dict[str, int] = {}
    for name, household in (("ana", first), ("ben", first), ("kim", other)):
        made[name] = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, %s) RETURNING id",
                                (household, name)))
    return made


def served(url: str, household: int) -> dict[int, bool]:
    """Read from the table at the revision under test, so a later revision's column cannot break an older step."""
    with psycopg.connect(url) as conn:
        return {int(r[0]): bool(r[1]) for r in conn.execute(
            "SELECT id, admin FROM people WHERE household_id = %s", (household,)).fetchall()}


def test_every_person_of_the_first_household_becomes_an_admin_and_no_one_else(empty_database: str) -> None:
    this, before = revision_named("people_admin")
    command.upgrade(alembic_config(empty_database), before)
    made = seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert served(empty_database, 1) == {made["ana"]: True, made["ben"]: True}
    assert served(empty_database, 2) == {made["kim"]: False}


def test_downgrading_takes_the_flag_away(empty_database: str) -> None:
    this, before = revision_named("people_admin")
    command.upgrade(alembic_config(empty_database), this)
    command.downgrade(alembic_config(empty_database), before)
    with psycopg.connect(empty_database) as conn:
        columns = {r[0] for r in conn.execute(
            "SELECT table_name || '.' || column_name FROM information_schema.columns "
            "WHERE column_name = 'admin' AND table_name IN ('people', 'sessions')").fetchall()}
    assert columns == set()
