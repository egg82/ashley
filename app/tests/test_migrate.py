"""The baseline migration, and the advisory lock that lets both sites run it at the same moment."""

import logging
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.__main__ import main
from ashley.db.migrate import LOCK_KEY, alembic_config, migrate

HEAD = ScriptDirectory.from_config(alembic_config("")).get_current_head()


def households_columns(url: str) -> dict[str, tuple[str, str, str | None, str]]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type, is_nullable, column_default, is_identity, identity_generation "
            "FROM information_schema.columns WHERE table_name = 'households'"
        ).fetchall()
    return {r[0]: (r[1], r[2], r[3], f"{r[4]}/{r[5]}") for r in rows}


class Forked:
    """`python -m ashley.db migrate`'s `main()` in a process forked from this one, its stdout on a pipe. A fresh
    interpreter would spend about a second of CPU importing psycopg, SQLAlchemy and alembic again; the fork has
    them already, and its CPU is still charged to the test when it is reaped."""

    def __init__(self, url: str) -> None:
        read, write = os.pipe()
        self.pid = os.fork()
        if self.pid == 0:
            os.close(read)
            code = 1
            try:
                sys.stdout = os.fdopen(write, "w")
                os.environ["DATABASE_URL"] = url
                code = main(["migrate"])
            except BaseException:
                traceback.print_exc()
            finally:
                sys.stdout.flush()
                os._exit(code)
        os.close(write)
        self.stdout = os.fdopen(read)

    def running(self) -> bool:
        return os.waitpid(self.pid, os.WNOHANG) == (0, 0)

    def communicate(self) -> tuple[int, str]:
        out = self.stdout.read()
        self.stdout.close()
        return os.waitstatus_to_exitcode(os.waitpid(self.pid, 0)[1]), out


def waiting_for_the_lock(url: str) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted AND objid = %s",
            (LOCK_KEY & 0xFFFFFFFF,),
        ).fetchone()
    return int(row[0]) if row else 0


def test_the_baseline_creates_households_with_an_identity_key(empty_database: str) -> None:
    migrate(empty_database)
    cols = households_columns(empty_database)
    assert set(cols) == {"id", "name", "created_at", "timezone", "profile", "locale", "unit_system", "clock", "latitude", "longitude"}
    assert cols["id"][0] == "bigint" and cols["id"][3] == "YES/ALWAYS"
    assert cols["name"][:2] == ("text", "NO")
    assert cols["created_at"][0] == "timestamp with time zone" and cols["created_at"][1] == "NO"
    assert cols["created_at"][2] == "now()"


def test_running_it_twice_changes_nothing(empty_database: str) -> None:
    migrate(empty_database)
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
def test_two_concurrent_runs_one_waits_and_the_schema_is_applied_once(
    empty_database: str, caplog: pytest.LogCaptureFixture
) -> None:
    """One contender is the command's `main()` in a forked process, the other `migrate()` on a thread. The lock
    serialises them, so the thread never shares alembic's module state with another run. The holder closes before
    the pool joins, so a failed assert releases the waiting thread instead of hanging until the timeout.

    The fork happens before the pool starts; the threads already running are pytest's, and the child touches only
    logging (reinitialised at fork), a stdout of its own and connections it opens."""
    caplog.set_level(logging.INFO, logger="ashley.db")
    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(empty_database, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        child = Forked(empty_database)
        thread = pool.submit(migrate, empty_database)
        deadline = time.monotonic() + 30
        while waiting_for_the_lock(empty_database) < 2:
            assert time.monotonic() < deadline, "both runs should be waiting on the lock"
            assert child.running() and not thread.done(), "a run finished while the lock was held"
            time.sleep(0.25)
        assert households_columns(empty_database) == {}, "nothing is applied while the lock is held"
        holder.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        thread.result(timeout=60)
    code, out = child.communicate()
    assert code == 0, out
    child_done = next(ln for ln in out.splitlines() if "event=migrate.done" in ln)
    records = [r for r in caplog.records if r.getMessage() == "migrate.done"]
    thread_done = [str(getattr(r, "fields", {}).get("revision_before")) for r in records]
    assert len(thread_done) == 1
    applied = sorted(["revision_before=none" in child_done, thread_done[0] == "none"])
    assert applied == [False, True], (child_done, thread_done)
    assert f"revision_after={HEAD}" in child_done and "event=migrate.lock_taken" in out
    assert set(households_columns(empty_database)) == {"id", "name", "created_at", "timezone", "profile", "locale", "unit_system", "clock", "latitude", "longitude"}


def test_conversations_from_before_the_channel_column_keep_it_null(empty_database: str) -> None:
    command.upgrade(alembic_config(empty_database), "0021")
    with psycopg.connect(empty_database) as conn:
        hid = conn.execute("INSERT INTO households (name, timezone) VALUES ('h', 'UTC') RETURNING id").fetchone()
        conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat')", hid)
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        assert conn.execute("SELECT channel, place FROM conversations").fetchall() == [(None, None)]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO conversations (household_id, kind, channel) VALUES (%s, 'chat', 'smoke')", hid)


def test_turns_from_before_answers_take_the_person_turn_they_followed_where_that_is_unambiguous(
        empty_database: str) -> None:
    command.upgrade(alembic_config(empty_database), "0035")
    with psycopg.connect(empty_database) as conn:
        hid = conn.execute("INSERT INTO households (name, timezone) VALUES ('h', 'UTC') RETURNING id").fetchone()
        assert hid is not None
        cid = conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                           hid).fetchone()
        assert cid is not None
        lines = [("person", False), ("ashley", True), ("ashley", False),
                 ("person", False), ("ashley", True), ("person", False), ("ashley", False), ("ashley", False),
                 ("ashley", False), ("person", False), ("ashley", True)]
        ids = [conn.execute("INSERT INTO turns (conversation_id, household_id, author, text, follows) "
                            "VALUES (%s, %s, %s, 'x', %s) RETURNING id", (cid[0], hid[0], who, follows)).fetchone()
               for who, follows in lines]
    ids = [row[0] for row in ids if row is not None]
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        got = dict(conn.execute("SELECT id, answers FROM turns").fetchall())
    p1, h1, a1, p2, h2, p3, x, y, z, p4, h4 = ids
    assert got == {p1: None, h1: p1, a1: p1, p2: None, h2: p2, p3: None, x: None, y: None, z: None, p4: None, h4: p4}


def test_a_wake_turn_stored_as_a_persons_becomes_the_households_and_other_turns_stay(empty_database: str) -> None:
    command.upgrade(alembic_config(empty_database), "0043")
    with psycopg.connect(empty_database) as conn:
        hid = conn.execute("INSERT INTO households (name, timezone) VALUES ('h', 'UTC') RETURNING id").fetchone()
        assert hid is not None
        pid = conn.execute("INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", hid).fetchone()
        assert pid is not None
        cid = conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                           hid).fetchone()
        assert cid is not None
        for source in ("wake:7", "discord:7", None):
            conn.execute("INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, source) "
                         "VALUES (%s, %s, 'person', %s, 'x', %s)", (cid[0], hid[0], pid[0], source))
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        assert conn.execute("SELECT author, speaker_id IS NULL, source FROM turns ORDER BY id").fetchall() == [
            ("household", True, "wake:7"), ("person", False, "discord:7"), ("person", False, None)]
