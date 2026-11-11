"""The migration that adds `people.admin` makes every person of the first household an admin and no one else: the
backfill keeps what a deployment's people could do before the flag existed."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar

BEFORE = "0103"


def seed(url: str) -> tuple[list[int], list[int]]:
    first = int(scalar(url, "INSERT INTO households (name) VALUES ('home') RETURNING id"))
    second = int(scalar(url, "INSERT INTO households (name) VALUES ('other') RETURNING id"))
    assert first == 1
    mine = [int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, %s) RETURNING id", (first, n)))
            for n in ("Alana", "Sam", "Ivy")]
    theirs = [int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Kim') RETURNING id", (second,)))]
    return mine, theirs


def admins(url: str) -> list[int]:
    with psycopg.connect(url) as conn:
        return [r[0] for r in conn.execute("SELECT id FROM people WHERE admin ORDER BY id").fetchall()]


def migrated(url: str) -> tuple[list[int], list[int]]:
    command.upgrade(alembic_config(url), BEFORE)
    people = seed(url)
    command.upgrade(alembic_config(url), "head")
    return people


def test_the_backfill_makes_every_first_household_person_admin(empty_database: str) -> None:
    mine, _ = migrated(empty_database)
    assert set(mine) <= set(admins(empty_database))


def test_the_backfill_makes_nobody_of_another_household_admin(empty_database: str) -> None:
    mine, theirs = migrated(empty_database)
    assert admins(empty_database) == sorted(mine)
    assert not set(theirs) & set(admins(empty_database))


def test_a_person_added_after_the_backfill_is_not_admin(empty_database: str) -> None:
    migrated(empty_database)
    late = int(scalar(empty_database, "INSERT INTO people (household_id, name) VALUES (1, 'Late') RETURNING id"))
    assert late not in admins(empty_database)
