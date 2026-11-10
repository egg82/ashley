"""The settings migration seeds no household, household 1 included: every connection starts with empty lists (read
back through the route, from a database migrated step by step)."""

import psycopg
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.migrate import alembic_config
from conn_settings_blind_support import People, app_client, as_, empty, read, session
from ashley.people import admin
from contract.conversations_support import scalar
from conn_settings_blind_support import the_house

SEEDED = ("household_reads", "service_reads", "reads")


def before_settings() -> str:
    script = ScriptDirectory.from_config(alembic_config(""))
    [found] = [r for r in script.walk_revisions() if r.path.endswith("_drop_watch_grant.py")]
    return found.revision


def test_household_one_starts_empty_like_any_other(empty_database: str) -> None:
    url = empty_database
    command.upgrade(alembic_config(url), before_settings())
    with psycopg.connect(url, autocommit=True) as conn:
        for name in ("Moore", "Other"):
            conn.execute("INSERT INTO households (name, timezone) VALUES (%s, 'UTC')", (name,))
    ids = [int(scalar(url, "SELECT id FROM households WHERE name = %s", (n,))) for n in ("Moore", "Other")]
    assert ids[0] == 1
    cids = [int(scalar(url, "INSERT INTO connections (household_id, kind, base_url, secret) "
                       "VALUES (%s, 'home_assistant', 'http://ha.test:8123', '\\x00') RETURNING id", (h,))) for h in ids]
    command.upgrade(alembic_config(url), "head")
    with psycopg.connect(url) as conn:
        persons = [admin.add_person(conn, h, f"P{h}") for h in ids]
        tokens = {"moore": session(conn, persons[0], ids[0], "m"), "other": session(conn, persons[1], ids[1], "o")}
    people = People(persons[0], persons[0], persons[1], ids[0], ids[1], tokens)
    with app_client(url, people, {ids[0]: the_house(), ids[1]: the_house()}) as client:
        as_(client, people, "moore")
        got = read(client, cids[0]).json()["values"]
        assert all(empty(got, k) for k in (*SEEDED, "consequential_entities"))
        as_(client, people, "other")
        other = read(client, cids[1]).json()["values"]
        assert all(empty(other, k) for k in (*SEEDED, "consequential_entities"))
