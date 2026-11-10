"""The migration's data move (found by what it drops, so a renumber changes nothing): each `herdr_watched` row becomes a
`claude_session` watch (hand-off, status and seq as the baseline, the kind's defaults, `expires_at` `handoff_hours` from
the migration), then `herdr_watched` is dropped; `wakes` gains kind `watch` with its `watch_id` and `changes`."""

from datetime import timedelta
from typing import Any

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar
from watch_turn_blind_support import KIND, revision_dropping

COLUMNS = ("person_id, household_id, kind, target, label, bench_id, armed_by, track, state, reason, failures, version, "
           "series, interval_s, baseline, when_clauses, until_clauses, expires_at, armed_at, tools")


def seed(url: str) -> tuple[int, int, int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    sam = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Sam') RETURNING id", (home,)))
    other = int(scalar(url, "INSERT INTO households (name) VALUES ('Elsewhere') RETURNING id"))
    insert = ("INSERT INTO herdr_watched (household_id, person_id, session_id, label, bench_id, status, seq) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING session_id")
    scalar(url, insert, (home, alana, "sess-a", "first", 5, "done", 1631))
    scalar(url, insert, (home, alana, "sess-b", "second", None, "working", 7))
    scalar(url, insert, (home, sam, "sess-a", "third", None, "blocked", 3))
    return home, alana, sam, other


def moved(url: str) -> dict[tuple[int, str], dict[str, Any]]:
    with psycopg.connect(url) as conn:
        cur = conn.execute(f"SELECT {COLUMNS} FROM watches")
        names = [d.name for d in cur.description or ()]
        return {(r[0], r[3]): dict(zip(names, r)) for r in cur.fetchall()}


def test_each_watched_session_becomes_a_hand_off_watch_from_the_state_recorded(empty_database: str) -> None:
    this, before = revision_dropping("herdr_watched")
    command.upgrade(alembic_config(empty_database), before)
    home, alana, sam, _ = seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    got = moved(empty_database)
    assert set(got) == {(alana, "sess-a"), (alana, "sess-b"), (sam, "sess-a")}
    first = got[(alana, "sess-a")]
    assert (first["household_id"], first["kind"], first["label"], first["bench_id"]) == (home, KIND, "first", 5)
    assert first["armed_by"] == "handoff" and list(first["track"]) == ["status", "seq"]
    assert first["baseline"] == {"sess-a": {"status": "done", "seq": 1631}}
    assert got[(alana, "sess-b")]["baseline"] == {"sess-b": {"status": "working", "seq": 7}}
    assert got[(sam, "sess-a")]["baseline"] == {"sess-a": {"status": "blocked", "seq": 3}}
    assert got[(sam, "sess-a")]["bench_id"] is None


def test_a_moved_watch_is_armed_with_the_kinds_defaults_and_no_history(empty_database: str) -> None:
    this, before = revision_dropping("herdr_watched")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    for row in moved(empty_database).values():
        assert (row["state"], row["reason"], row["failures"], row["series"]) == ("armed", None, 0, 0)
        assert row["interval_s"] == 15 and row["tools"] is None
        assert len(row["when_clauses"]) == 2 and len(row["until_clauses"]) == 1
        assert "gone" in str(row["until_clauses"])


def test_a_moved_watch_lasts_the_hand_off_hours_from_the_migration(empty_database: str) -> None:
    this, before = revision_dropping("herdr_watched")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    started = scalar(empty_database, "SELECT now()")
    command.upgrade(alembic_config(empty_database), this)
    ended = scalar(empty_database, "SELECT clock_timestamp()")
    for row in moved(empty_database).values():
        assert started + timedelta(hours=72) <= row["expires_at"] <= ended + timedelta(hours=72)


def test_the_old_table_is_gone_and_wakes_can_hold_a_watch(empty_database: str) -> None:
    this, before = revision_dropping("herdr_watched")
    command.upgrade(alembic_config(empty_database), before)
    seed(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert scalar(empty_database, "SELECT to_regclass('herdr_watched')::text") is None
    names = {r[0] for r in psycopg.connect(empty_database).execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'wakes'").fetchall()}
    assert {"watch_id", "changes"} <= names


def test_a_database_that_watched_nothing_comes_across_empty(empty_database: str) -> None:
    this, before = revision_dropping("herdr_watched")
    command.upgrade(alembic_config(empty_database), before)
    command.upgrade(alembic_config(empty_database), this)
    assert int(scalar(empty_database, "SELECT count(*) FROM watches")) == 0
    assert scalar(empty_database, "SELECT to_regclass('herdr_watched')::text") is None
