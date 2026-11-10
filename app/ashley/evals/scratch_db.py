"""A throwaway database beside the one an admin URL names, for an eval that writes: made for the run and dropped after,
so the real database's rows are untouched."""

import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


def create(admin_url: str) -> tuple[str, str]:
    """A new empty database beside the one `admin_url` names: its name and connection string."""
    name = f"ashley_eval_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name, make_conninfo(admin_url, dbname=name)


def drop(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
