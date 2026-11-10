"""Throwaway databases on the server `ASHLEY_TEST_DATABASE_URL` names, one per test that needs the schema."""

import os
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

ENV = "ASHLEY_TEST_DATABASE_URL"


def admin_url() -> str:
    """The server to create databases on. Unset fails under CI (`CI=true`), so the database tests cannot silently
    stop running there; locally it skips, with the reason."""
    url = os.environ.get(ENV)
    if url:
        return url
    if os.environ.get("CI") == "true":
        pytest.fail(f"{ENV} is unset under CI: the database tests must run there")
    pytest.skip(f"{ENV} is unset: no Postgres to test against (CI sets it)")


@contextmanager
def throwaway_database() -> Generator[str]:
    """Create an empty database and yield its connection string; drop it afterwards."""
    admin = admin_url()
    name = f"ashley_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(admin, dbname=name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
