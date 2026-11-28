"""The reminder-turns migration makes each reminder, errand check or standing round stored as the person's turn the
household's, its text the line the page shows, and leaves every real person turn as it was."""

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


PROMPT = ("[A reminder you set, not words anyone said: for Alana; they asked you to remind them.]\n"
          "What to remind them of: pay the card\nRemind Alana of it now, briefly, in your own words.")
ERRAND = "[An errand you are carrying out over time, not words anyone said: for Alana; they asked you to do it.]\nx"


def wake(url: str, home: int, alana: int, brief: str, ends: bool = False) -> int:
    return int(scalar(url, "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, "
                           "brief, ends_at) VALUES (%s, 'reminder', %s, 'reminder', now(), now(), %s, %s, %s, "
                           "CASE WHEN %s THEN now() + interval '1 day' END) RETURNING id",
                      (home, brief, alana, alana, brief, ends)))


def test_old_reminder_turns_become_the_household_s_line_and_person_turns_stay(empty_database: str) -> None:
    this, before = revision_named("reminder_turns_household")
    command.upgrade(alembic_config(empty_database), before)
    url = empty_database
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    talk = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))
    plain, errand = wake(url, home, alana, "pay the card"), wake(url, home, alana, "find a plumber", ends=True)
    rows = (("person", alana, PROMPT, f"wake:{plain}", "private"),
            ("person", alana, ERRAND, f"wake:{errand}", "private"),
            ("person", alana, PROMPT, f"wake:{plain}0", "shared"),
            ("person", alana, ERRAND, "wake:999999", "private"),
            ("person", alana, PROMPT, None, "private"),
            ("person", alana, "said it", "discord:3", "shared"),
            ("ashley", None, "hi", None, "private"))
    for author, speaker, text, source, heard in rows:
        scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, source, visibility) "
                    "SELECT id, household_id, %s, %s, %s, %s, %s FROM conversations WHERE id = %s RETURNING id",
               (author, speaker, text, source, heard, talk))
    command.upgrade(alembic_config(url), this)
    with psycopg.connect(url) as conn:
        got = conn.execute("SELECT author, speaker_id, text FROM turns ORDER BY id").fetchall()
    assert got == [("household", None, "Reminder: pay the card"),
                   ("household", None, "Errand check: find a plumber"),
                   ("household", None, "Reminder for Alana"),
                   ("household", None, "Errand check"),
                   ("person", alana, PROMPT),
                   ("person", alana, "said it"),
                   ("ashley", None, "hi")]
