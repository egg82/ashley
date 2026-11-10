"""The migration that renames the `authentik` account system to `oidc`, found by its name so a renumber changes
nothing: accounts and refused sign-ins on `authentik` come across as `oidc`, every other system is left alone, and
downgrading puts them back."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar
from test_proposals_migration import revision_named


def seed(url: str) -> None:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    for system, external_id in (("authentik", "sub-a"), ("discord", "d-1"), ("home_assistant", "ha-1")):
        scalar(url, "INSERT INTO accounts (household_id, person_id, system, external_id) VALUES (%s, %s, %s, %s) "
                    "RETURNING 1", (home, alana, system, external_id))
    scalar(url, "INSERT INTO signin_unmapped (system, external_id, username) VALUES ('authentik', 'sub-u', 'u') "
                "RETURNING 1")


def systems(url: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    with psycopg.connect(url) as conn:
        accounts = conn.execute("SELECT system, external_id FROM accounts ORDER BY external_id").fetchall()
        refused = conn.execute("SELECT system, external_id FROM signin_unmapped").fetchall()
    return accounts, refused


def test_authentik_rows_become_oidc_and_other_systems_are_left_alone(empty_database: str) -> None:
    this, before = revision_named("accounts_authentik_to_oidc")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert systems(empty_database) == (
        [("discord", "d-1"), ("home_assistant", "ha-1"), ("oidc", "sub-a")], [("oidc", "sub-u")])


def test_downgrading_puts_the_authentik_rows_back(empty_database: str) -> None:
    this, before = revision_named("accounts_authentik_to_oidc")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    command.downgrade(alembic_config(empty_database), before)
    assert systems(empty_database) == (
        [("discord", "d-1"), ("home_assistant", "ha-1"), ("authentik", "sub-a")], [("authentik", "sub-u")])
