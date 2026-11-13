"""A pooled database is indistinguishable from a fresh clone of the migrated template, whatever the test before it left
in its own database, and the pool leaves no database behind."""

import psycopg
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template, scalar
from db_pool import DatabasePool
from pg import admin_url
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

TABLES = """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY 1"""
SEQUENCES = "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace " \
            "WHERE c.relkind = 'S' AND n.nspname = 'public' ORDER BY 1"


def state(url: str) -> dict[str, object]:
    """Every public table's row count and every sequence's position, plus what the server holds for this database
    besides the connection reading it."""
    name = conninfo_to_dict(url)["dbname"]
    with psycopg.connect(url, autocommit=True) as conn:
        counts = {t: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t))).fetchone()
                  for (t,) in conn.execute(TABLES).fetchall()}
        positions = {s: conn.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(sql.Identifier(s)))
                     .fetchone() for (s,) in conn.execute(SEQUENCES).fetchall()}
        others = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                              (name,)).fetchone()
        advisory = conn.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND database = "
                                "(SELECT oid FROM pg_database WHERE datname = %s)", (name,)).fetchone()
        prepared = conn.execute("SELECT count(*) FROM pg_prepared_xacts WHERE database = %s", (name,)).fetchone()
    return {"rows": counts, "sequences": positions, "other_connections": others, "advisory_locks": advisory,
            "prepared": prepared}


def dirty(url: str) -> list[psycopg.Connection]:
    """Leave everything a test can leave in its database, and the connections open."""
    household(url)
    household(url)
    scalar(url, "SELECT nextval(pg_get_serial_sequence('households', 'id'))")
    held = [psycopg.connect(url, autocommit=True) for _ in range(2)]
    held[0].execute("SELECT pg_advisory_lock(42)")
    held[1].execute("LISTEN leftover_channel")
    with psycopg.connect(url, autocommit=True) as conn:
        if conn.execute("SHOW max_prepared_transactions").fetchone() != ("0",):
            conn.execute("BEGIN")
            conn.execute("INSERT INTO households (name) VALUES ('prepared')")
            conn.execute("PREPARE TRANSACTION 'leftover'")
    return held


def test_a_database_the_pool_hands_out_is_a_fresh_clone_whatever_the_last_test_left(
        migrated_template: DatabasePool) -> None:
    admin = admin_url()
    fresh = state(make_conninfo(admin, dbname=migrated_template.template))
    first = migrated_template.take()
    held = dirty(first)
    try:
        used = state(first)
        assert used != fresh, "the setup left nothing to reset"
        assert used["advisory_locks"] != (0,) and used["other_connections"] != (0,)
        migrated_template.release(first)
        for _ in range(3):
            url = migrated_template.take()
            assert state(url) == fresh
            migrated_template.release(url)
    finally:
        for conn in held:
            conn.close()


def test_a_closed_pool_has_dropped_every_database_it_made_even_one_a_test_left_connected(
        migrated_template: DatabasePool) -> None:
    pool = DatabasePool(admin_url(), migrated_template.template)
    taken = [pool.take(), pool.take()]
    held = dirty(taken[0])
    names = [conninfo_to_dict(url)["dbname"] for url in taken] + [pool.spare()]
    for url in taken:
        pool.release(url)
    pool.close()
    for conn in held:
        conn.close()
    with psycopg.connect(admin_url(), autocommit=True) as conn:
        left = conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'ashley_test_%%'").fetchall()
    assert not {n for (n,) in left} & set(names)
