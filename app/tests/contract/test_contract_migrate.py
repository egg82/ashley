"""`ashley.db.migrate`: head on an empty database, idempotent, safe to run at the same moment from two sites."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from ashley.db.migrate import migrate, revision
from pg import throwaway_database

Conn = psycopg.Connection[tuple[object, ...]]


def tables(conn: Conn) -> set[str]:
    rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()
    return {str(r[0]) for r in rows}


def columns(conn: Conn, table: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = %s",
        (table,),
    ).fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def snapshot(conn: Conn) -> dict[str, dict[str, str]]:
    return {t: columns(conn, t) for t in sorted(tables(conn))}


def test_an_empty_database_is_at_revision_none(empty_database: str) -> None:
    with psycopg.connect(empty_database) as conn:
        assert revision(conn) == "none"


def test_migrate_reaches_head_and_creates_households(empty_database: str) -> None:
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        assert revision(conn) != "none"
        assert "households" in tables(conn)
        assert columns(conn, "households"), "households has no columns"


def test_a_turn_stores_no_memory_outcome(empty_database: str) -> None:
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        assert columns(conn, "turns"), "turns has no columns"
        assert "kept" not in columns(conn, "turns")


def test_households_has_a_single_column_primary_key(empty_database: str) -> None:
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        keys = conn.execute(
            "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
            "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = 'public.households'::regclass AND i.indisprimary"
        ).fetchall()
    assert len(keys) == 1


NOT_HOUSEHOLD_DATA = {
    "households": "the households themselves",
    "alembic_version": "the migration tool's own",
    "inference_calls": "the deployment's API spend: kinds, models and tokens, nothing said or known about anyone",
    "discord_seen": "which Discord messages were claimed for a reply: Discord's ids and a time, nothing said",
    "device_requests": "how many requests each device made in a window: a device id, a time and a count, nothing said",
    "signin_pending": "a sign-in in flight: hashed state, a PKCE verifier, a nonce and a path, before anyone is known",
    "signin_unmapped": "OIDC accounts refused because no person has them, so no household either",
    "proton_bridge": "the one Bridge the deployment runs: its vault holds every household's Proton sessions at once, and its epoch and heartbeat say nothing about any one",
    "model_catalogue_fetch": "models.dev's public list of models and prices, one row for the deployment",
    "model_catalogue_overrides": "an admin's deployment-wide corrections to that list: a model's field and who set it",
    "file_orphans": "object-store keys the sweep found unreferenced, which name their household and file hash and span households",
    "deployment_secrets": "the deployment's own keys (the file link key, her Web Push key pair), sealed, one row per key and nothing about any household",
}


def test_every_table_but_households_carries_household_id(empty_database: str) -> None:
    """decisions.md: `household_id` is on every row of household data from the first migration."""
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        seen = [t for t in tables(conn) if t not in NOT_HOUSEHOLD_DATA]
        assert "turns" in seen
        for t in seen:
            assert "household_id" in columns(conn, t), t


def test_migrating_twice_changes_nothing(empty_database: str) -> None:
    migrate(empty_database)
    with psycopg.connect(empty_database, autocommit=True) as conn:
        conn.execute("INSERT INTO households (name) VALUES ('kept')")
        before = (revision(conn), snapshot(conn))
    migrate(empty_database)
    with psycopg.connect(empty_database) as conn:
        assert (revision(conn), snapshot(conn)) == before
        assert conn.execute("SELECT name FROM households").fetchall() == [("kept",)]


def test_a_failed_connection_raises_rather_than_passing_silently() -> None:
    with pytest.raises(Exception):
        migrate("host=127.0.0.1 port=1 dbname=x user=postgres connect_timeout=2")


@pytest.mark.parametrize("round_", range(3))
def test_two_concurrent_runs_both_succeed_and_the_schema_is_applied_once(round_: int) -> None:
    with throwaway_database() as url, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(migrate, url) for _ in range(2)]
        for f in futures:
            f.result(timeout=60)
        with psycopg.connect(url) as conn:
            versions = conn.execute("SELECT count(*) FROM alembic_version").fetchone()
            assert versions == (1,)
            assert "households" in tables(conn)
            assert revision(conn) != "none"
