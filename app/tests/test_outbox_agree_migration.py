"""The migration that drops `outbox.agree`, found by its name: the column is gone after it, the receipts column keeps
its rows, and downgrading brings the column back nullable."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar
from test_proposals_migration import revision_named


def columns(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        return {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'outbox'").fetchall()}


def test_the_agree_column_goes_and_receipts_stay_and_downgrading_brings_it_back_empty(empty_database: str) -> None:
    this, before = revision_named("drop_outbox_agree")
    command.upgrade(alembic_config(empty_database), before)
    home = int(scalar(empty_database, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    conversation = int(scalar(empty_database, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))
    scalar(empty_database, "INSERT INTO outbox (household_id, thread, conversation_id, medium, body, agree, receipts) "
                           "VALUES (%s, 'push:1', %s, 'text', 'hi', 9, '{\"done\": []}') RETURNING 1", (home, conversation))
    assert "agree" in columns(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert "agree" not in columns(empty_database) and "receipts" in columns(empty_database)
    assert scalar(empty_database, "SELECT receipts->'done' FROM outbox") == []
    command.downgrade(alembic_config(empty_database), before)
    assert "agree" in columns(empty_database)
    assert scalar(empty_database, "SELECT agree FROM outbox") is None
