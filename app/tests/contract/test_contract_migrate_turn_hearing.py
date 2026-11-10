"""Migration 0026 on turns from before it: a web conversation with one participant becomes theirs, privately; every
other turn is heard by no one, since nothing stored says who could hear it."""

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config, migrate

Conn = psycopg.Connection[tuple[object, ...]]


def _person(conn: Conn, name: str) -> int:
    row = conn.execute("INSERT INTO people (household_id, name) VALUES (1, %s) RETURNING id", (name,)).fetchone()
    assert row is not None
    return int(str(row[0]))


def _conversation(conn: Conn, channel: str | None, people: list[int]) -> int:
    row = conn.execute("INSERT INTO conversations (household_id, kind, channel) VALUES (1, 'chat', %s) RETURNING id",
                       (channel,)).fetchone()
    assert row is not None
    conversation = int(str(row[0]))
    for person in people:
        conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                     "VALUES (%s, 1, %s)", (conversation, person))
    conn.execute("INSERT INTO turns (conversation_id, household_id, author, speaker_id, text) VALUES "
                 "(%s, 1, 'person', %s, 'hello'), (%s, 1, 'ashley', NULL, 'hi')",
                 (conversation, people[0] if people else None, conversation))
    return conversation


def test_a_one_person_web_conversation_becomes_theirs_and_nothing_else_is_heard(empty_database: str) -> None:
    command.upgrade(alembic_config(empty_database), "0025")
    with psycopg.connect(empty_database, autocommit=True) as conn:
        conn.execute("INSERT INTO households (name) VALUES ('h')")
        alana, sam = _person(conn, "Alana"), _person(conn, "Sam")
        web = _conversation(conn, "web", [alana])
        web_two = _conversation(conn, "web", [alana, sam])
        discord = _conversation(conn, "discord", [alana])
        unknown = _conversation(conn, None, [alana])
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        rows = conn.execute("SELECT conversation_id, visibility, owner_id FROM turns ORDER BY id").fetchall()
    heard = {(int(str(c)), str(v), o) for c, v, o in rows}
    assert heard == {(web, "private", alana), (web_two, "private", None), (discord, "private", None),
                     (unknown, "private", None)}
