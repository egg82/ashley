"""Migration 0051 (`bench_reactions`) over a real database: it follows 0050, what it creates, and what it does with
benches that had work before it. The repository's migrations run forward only, so there is no down step to take."""

import json
import uuid
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from ashley.channels.wake.bench_react_config import CONFIG
from ashley.db.migrate import alembic_config
from contract.conversations_support import admin_url, household, person, scalar
from psycopg import sql
from psycopg.conninfo import make_conninfo

ADD = json.dumps({"type": "add"})


@pytest.fixture
def at_0050() -> Generator[str]:
    """A database migrated to 0050 and nothing further."""
    admin = admin_url()
    name = f"ashley_mig_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(admin, dbname=name)
    try:
        command.upgrade(alembic_config(url), "0050")
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def exists(url: str) -> bool:
    return bool(scalar(url, "SELECT to_regclass('public.bench_reactions') IS NOT NULL"))


def bench(url: str, home: int, owner: int) -> int:
    return int(scalar(url, "INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, 'b') RETURNING id",
                      (home, owner)))


def command_row(url: str, b: int, home: int, seq: int, who: int | None, outcome: str) -> None:
    effect = "'{}'::jsonb" if outcome == "accepted" else "NULL"
    scalar(url, f"WITH i AS (INSERT INTO bench_commands (bench_id, household_id, seq, person_id, command, outcome, effect)"
                f" VALUES (%s, %s, %s, %s, %s::jsonb, %s, {effect}) RETURNING 1) SELECT count(*) FROM i",
           (b, home, seq, who, ADD, outcome))


def test_0051_follows_0050_and_is_the_head_the_branch_adds() -> None:
    script = ScriptDirectory.from_config(alembic_config("postgresql://unused"))
    revision = script.get_revision("0051")
    assert revision is not None and revision.down_revision == "0050"


def test_the_table_is_absent_at_0050_and_present_after_0051(at_0050: str) -> None:
    assert not exists(at_0050)
    command.upgrade(alembic_config(at_0050), "0051")
    assert exists(at_0050)


def test_the_table_rejects_a_mark_below_one_and_a_bench_that_does_not_exist(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.Error):
            conn.execute("INSERT INTO bench_reactions (bench_id, household_id, to_seq) VALUES (1, 1, 1)")
    home = household(db_url)
    owner = person(db_url, home)
    b = bench(db_url, home, owner)
    with psycopg.connect(db_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.Error):
            conn.execute("INSERT INTO bench_reactions (bench_id, household_id, to_seq) VALUES (%s, %s, 0)", (b, home))


def test_up_marks_a_bench_with_earlier_work_at_the_persons_newest_accepted_command_not_hers(at_0050: str) -> None:
    url = at_0050
    home = household(url)
    owner = person(url, home)
    worked, only_hers, only_refused, empty = (bench(url, home, owner) for _ in range(4))
    for seq, who, outcome in ((1, owner, "accepted"), (2, None, "accepted"), (3, owner, "accepted"),
                              (4, None, "accepted"), (5, owner, "changed_since")):
        command_row(url, worked, home, seq, who, outcome)
    command_row(url, only_hers, home, 1, None, "accepted")
    command_row(url, only_refused, home, 1, owner, "changed_since")
    command.upgrade(alembic_config(url), "0051")
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT bench_id, to_seq, extract(epoch FROM now() - at) FROM bench_reactions").fetchall()
    got = {row[0]: (row[1], row[2]) for row in rows}
    assert set(got) == {worked} and empty not in got
    seq, age = got[worked]
    assert seq == 3 and age > CONFIG.window_s
