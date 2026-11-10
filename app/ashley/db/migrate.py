"""Schema migrations: a separate command (`python -m ashley.db migrate`), never run by the app.

Both sites start it at the same moment against the same primary, so the upgrade holds a Postgres session advisory
lock: the second run waits, then finds nothing to do."""

import logging
import time
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config

from .. import logs

log = logging.getLogger("ashley.db")

LOCK_KEY = 7_283_194_001_002
HERE = Path(__file__).resolve().parent


def alembic_config(conninfo: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(HERE / "alembic"))
    cfg.attributes["conninfo"] = conninfo
    return cfg


def revision(conn: psycopg.Connection[tuple[object, ...]]) -> str:
    """The schema's current revision, `none` before the first migration."""
    if not conn.execute("SELECT to_regclass('alembic_version') IS NOT NULL").fetchone() == (True,):
        return "none"
    row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else "none"


def migrate(conninfo: str) -> None:
    """Upgrade to head while holding the advisory lock on a connection of its own, released when it closes."""
    started = time.perf_counter()
    with psycopg.connect(conninfo, autocommit=True) as lock:
        logs.info(log, "migrate.lock_waiting", key=LOCK_KEY)
        lock.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        waited = time.perf_counter() - started
        logs.info(log, "migrate.lock_taken", key=LOCK_KEY, ms=int(waited * 1000))
        before = revision(lock)
        try:
            command.upgrade(alembic_config(conninfo), "head")
            after = revision(lock)
        finally:
            lock.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            logs.info(log, "migrate.lock_released", key=LOCK_KEY)
    logs.info(log, "migrate.done", revision_before=before, revision_after=after,
              ms=int((time.perf_counter() - started) * 1000))
