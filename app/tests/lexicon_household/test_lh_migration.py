"""The household-lexicon migration seeds no household, household 1 included, from a database migrated step by step."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar


def test_household_one_starts_with_no_words_like_any_other(empty_database: str) -> None:
    url = empty_database
    command.upgrade(alembic_config(url), "0085")
    with psycopg.connect(url, autocommit=True) as conn:
        for name in ("Moore", "Other"):
            conn.execute("INSERT INTO households (name, timezone) VALUES (%s, 'UTC')", (name,))
    command.upgrade(alembic_config(url), "0086")
    assert scalar(url, "SELECT count(*) FROM household_lexicon") == 0
