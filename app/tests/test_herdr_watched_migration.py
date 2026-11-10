"""The migration that moves the session sense onto Watches, found by its name so a renumber changes nothing: each row of
`herdr_watched` comes across as a `claude_session` hand-off watch whose baseline is the status and seq recorded and whose
conditions are the kind's, the old table is gone, and downgrading brings back the empty table."""

import psycopg
from alembic import command
from ashley.criteria import condition
from ashley.db.migrate import alembic_config
from ashley.watches.config import CONFIG
from contract.conversations_support import scalar
from test_proposals_migration import revision_named

KIND = CONFIG.kinds["claude_session"]


def seed(url: str) -> tuple[int, int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    sam = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Sam') RETURNING id", (home,)))
    insert = ("INSERT INTO herdr_watched (household_id, person_id, session_id, label, bench_id, status, seq) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING 1")
    scalar(url, insert, (home, alana, "s-one", "first", 4, "working", 1001))
    scalar(url, insert, (home, alana, "s-two", "second", None, "done", 7))
    scalar(url, insert, (home, sam, "s-one", "first", None, "idle", 12))
    return home, alana, sam


def watches(url: str) -> list[tuple[int, str, str, str, int | None, str, dict[str, dict[str, object]], str]]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT person_id, kind, target, label, bench_id, armed_by, baseline, state FROM watches "
                            "ORDER BY person_id, target").fetchall()


def test_each_watched_session_becomes_a_hand_off_watch_from_the_state_recorded(empty_database: str) -> None:
    this, before = revision_named("herdr_watched_to_watches")
    command.upgrade(alembic_config(empty_database), before)
    _, alana, sam = seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert watches(empty_database) == [
        (alana, "claude_session", "s-one", "first", 4, "handoff", {"s-one": {"status": "working", "seq": 1001}}, "armed"),
        (alana, "claude_session", "s-two", "second", None, "handoff", {"s-two": {"status": "done", "seq": 7}}, "armed"),
        (sam, "claude_session", "s-one", "first", None, "handoff", {"s-one": {"status": "idle", "seq": 12}}, "armed")]
    assert scalar(empty_database, "SELECT to_regclass('herdr_watched') IS NULL") is True


def test_the_watches_carry_the_kinds_defaults_as_of_the_migration(empty_database: str) -> None:
    this, before = revision_named("herdr_watched_to_watches")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    with psycopg.connect(empty_database) as conn:
        rows = conn.execute("SELECT track, when_clauses, until_clauses, tools, interval_s, "
                            "extract(epoch FROM expires_at - now()) / 3600 FROM watches").fetchall()
    assert len(rows) == 3
    for track, when, until, tools, interval_s, hours in rows:
        assert tuple(track) == KIND.track and condition.from_json(when) == KIND.when
        assert condition.from_json(until) == KIND.handoff_until and tools is None and interval_s == KIND.interval_s
        assert abs(float(hours) - KIND.handoff_hours) < 0.1


def test_downgrading_brings_back_the_empty_table_and_upgrading_again_works(empty_database: str) -> None:
    this, before = revision_named("herdr_watched_to_watches")
    command.upgrade(alembic_config(empty_database), this)
    command.downgrade(alembic_config(empty_database), before)
    assert scalar(empty_database, "SELECT count(*) FROM herdr_watched") == 0
    command.upgrade(alembic_config(empty_database), this)
    assert scalar(empty_database, "SELECT to_regclass('herdr_watched') IS NULL") is True
