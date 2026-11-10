"""The members-visibility migration: money no owner said who may know becomes the household's; what an owner stated, and every other
kind, is left as it was."""

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


def test_unstated_money_becomes_members_with_no_owner_and_everything_else_is_untouched(empty_database: str) -> None:
    url = empty_database
    this, before = revision_named("members_visibility")
    command.upgrade(alembic_config(url), before)
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    talk = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))
    ids: dict[str, int] = {}
    for name, kind, stated, visibility in (("unstated", "finance", False, "private"), ("stated", "finance", True, "private"),
                                           ("told", "finance", True, "discreet"), ("health", "health", False, "private"),
                                           ("tea", "preference", False, "shared")):
        ids[name] = int(scalar(url, "INSERT INTO facts (household_id, about_id, owner_id, visibility, visibility_stated, "
                                    "kind, standing, text, source_conversation_id, valid_from) "
                                    "VALUES (%s, %s, %s, %s, %s, %s, false, %s, %s, now()) RETURNING id",
                               (home, alana, alana, visibility, stated, kind, name, talk)))
    command.upgrade(alembic_config(url), this)
    with psycopg.connect(url) as conn:
        rows = {r[0]: r[1:] for r in conn.execute("SELECT id, about_id, owner_id, visibility FROM facts").fetchall()}
    assert rows[ids["unstated"]] == (alana, None, "members")
    assert rows[ids["stated"]] == (alana, alana, "private")
    assert rows[ids["told"]] == (alana, alana, "discreet")
    assert rows[ids["health"]] == (alana, alana, "private")
    assert rows[ids["tea"]] == (alana, alana, "shared")
