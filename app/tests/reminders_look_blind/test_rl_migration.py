"""The migration that adds `wakes.landed`, found by its name so a renumber changes nothing: from the prior head it adds
one nullable JSON column, keeps every row, leaves old rows without a deposit, and the store then works on the schema after the later migrations."""

from datetime import UTC, datetime

import psycopg
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.migrate import alembic_config
from ashley.db.pool import PoolDatabase
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Reminder
from contract.conversations_support import run, scalar
from reminders_look_blind_support import LANDED

COLUMN = "SELECT data_type, is_nullable FROM information_schema.columns WHERE table_name = 'wakes' AND column_name = 'landed'"


def revision_named(name: str) -> tuple[str, str]:
    """(revision, its parent) of the migration whose file is named `<id>_<name>.py`, so a renumber changes nothing."""
    script = ScriptDirectory.from_config(alembic_config(""))
    [found] = [r for r in script.walk_revisions() if r.path.endswith(f"_{name}.py")]
    assert isinstance(found.down_revision, str)
    return found.revision, found.down_revision


def columns(url: str) -> list[tuple[str, str]]:
    with psycopg.connect(url) as conn:
        return conn.execute(COLUMN).fetchall()


def test_from_the_prior_head_it_adds_one_nullable_json_column(empty_database: str) -> None:
    this, before = revision_named("reminder_landed")
    command.upgrade(alembic_config(empty_database), before)
    assert columns(empty_database) == []
    command.upgrade(alembic_config(empty_database), this)
    assert columns(empty_database) == [("jsonb", "YES")]


def seed_old_rows(url: str) -> tuple[int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    for i in range(3):
        scalar(url, "INSERT INTO wakes (household_id, event_id, event, at, kind, due_at, person_id, made_by, brief) "
                    "VALUES (%s, %s, 'reminder', now(), 'reminder', now() - interval '1 minute', %s, %s, %s) RETURNING id",
               (home, f"old-{i}", alana, alana, f"old brief {i}"))
    return home, alana


def test_rows_from_before_survive_with_no_deposit_and_are_read_as_reminders(empty_database: str) -> None:
    this, before = revision_named("reminder_landed")
    command.upgrade(alembic_config(empty_database), before)
    seed_old_rows(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert int(scalar(empty_database, "SELECT count(*) FROM wakes")) == 3
    assert int(scalar(empty_database, "SELECT count(*) FROM wakes WHERE landed IS NULL")) == 3
    command.upgrade(alembic_config(empty_database), "head")

    async def go() -> None:
        db = PoolDatabase(empty_database, connect_timeout_s=5.0)
        await db.open()
        try:
            due = await PostgresWakes(db).due(10)
            got = sorted((d.wake.brief, d.wake.landed) for d in due if isinstance(d.wake, Reminder))
            assert got == [(f"old brief {i}", None) for i in range(3)]
        finally:
            await db.close()

    run(go())


def test_a_deposit_reminder_is_stored_on_the_migrated_schema(empty_database: str) -> None:
    this, before = revision_named("reminder_landed")
    command.upgrade(alembic_config(empty_database), before)
    home, alana = seed_old_rows(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    command.upgrade(alembic_config(empty_database), "head")

    async def go() -> None:
        db = PoolDatabase(empty_database, connect_timeout_s=5.0)
        await db.open()
        try:
            deposits = PostgresDeposits(db)
            armed = await deposits.arm(Reminder(home, alana, alana, "split it", datetime.now(UTC), None),
                                       DepositRule("acct", "Checking", 100, "Acme", "contains"))
            assert await deposits.fire(armed, "t1", LANDED) is True
            assert await deposits.fire(armed, "t1", LANDED) is False
            found = [d.wake for d in await PostgresWakes(db).due(10) if isinstance(d.wake, Reminder)]
            assert [w.landed for w in found if w.brief == "split it"] == [LANDED]
            assert [w.landed for w in found if w.brief != "split it"] == [None, None, None]
        finally:
            await db.close()

    run(go())


def test_running_it_again_is_a_no_op(empty_database: str) -> None:
    this, _ = revision_named("reminder_landed")
    command.upgrade(alembic_config(empty_database), this)
    command.upgrade(alembic_config(empty_database), this)
    assert columns(empty_database) == [("jsonb", "YES")]
