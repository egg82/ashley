"""The household-turns migration turns the person turns an old wake stored into the household's."""

import psycopg
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar


def revision_named(name: str) -> tuple[str, str]:
    """(revision, its parent) of the migration whose file is named `<id>_<name>.py`, so a renumber changes nothing."""
    script = ScriptDirectory.from_config(alembic_config(""))
    [found] = [r for r in script.walk_revisions() if r.path.endswith(f"_{name}.py")]
    assert isinstance(found.down_revision, str)
    return found.revision, found.down_revision


def seed(url: str) -> tuple[int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    talk = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))
    return alana, talk


def test_old_person_turns_with_a_wake_source_become_household_turns_with_no_speaker(empty_database: str) -> None:
    this, before = revision_named("household_turns")
    command.upgrade(alembic_config(empty_database), before)
    alana, talk = seed(empty_database)
    for author, speaker, text, source in (("person", alana, "wake text", "wake:3"), ("person", alana, "said it", None),
                                          ("person", alana, "discord one", "discord:3"), ("ashley", None, "hi", None)):
        scalar(empty_database, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, source) "
                               "SELECT id, household_id, %s, %s, %s, %s FROM conversations WHERE id = %s RETURNING id",
               (author, speaker, text, source, talk))
    command.upgrade(alembic_config(empty_database), this)
    with psycopg.connect(empty_database) as conn:
        rows = conn.execute("SELECT text, author, speaker_id, source FROM turns ORDER BY id").fetchall()
    assert rows == [("wake text", "household", None, "wake:3"), ("said it", "person", alana, None),
                    ("discord one", "person", alana, "discord:3"), ("hi", "ashley", None, None)]


def test_a_household_turn_can_be_stored_after_the_migration(empty_database: str) -> None:
    command.upgrade(alembic_config(empty_database), revision_named("household_turns")[0])
    _, talk = seed(empty_database)
    scalar(empty_database, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "SELECT id, household_id, 'household', 'e' FROM conversations WHERE id = %s RETURNING id",
           (talk,))
