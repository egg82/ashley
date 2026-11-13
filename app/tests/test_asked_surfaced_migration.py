"""The migration that turns a guessed number's stored `asked: true` into a `Surfaced` (found by its name, so a renumber
changes nothing): the bench's log gains a `Surfaced` of hers per piece, naming each such number as the person is shown it,
and the key is gone from every body, the log's included."""

import json

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from ashley.workshop.codec import decode_command, decode_effect
from ashley.workshop.commands import Shown, ShownRow, Surfaced
from ashley.workshop.model import By
from contract.conversations_support import scalar
from test_proposals_migration import revision_named

ASKED = json.dumps({"items": [
    {"name": "strap_width", "value": 15.0, "unit": "mm", "source": "guessed", "asked": True},
    {"name": "rim", "value": 2.5, "unit": "mm", "source": "guessed", "asked": False},
    {"name": "hole", "value": 6, "unit": "mm", "source": "measured"},
    {"kind": "choice", "name": "form", "label": "The strap", "value": "flat", "source": "guessed"}]})
OUTSIDE_ASKED = json.dumps({"items": [{"name": "x", "value": 1, "unit": "mm", "source": "guessed", "asked": True}]})


def seed(url: str, body: str = ASKED) -> tuple[int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    bench = int(scalar(url, "INSERT INTO benches (household_id, owner_id, title, next_seq) VALUES (%s, %s, 'Strap', 3) "
                       "RETURNING id", (home, alana)))
    insert = ("INSERT INTO bench_pieces (bench_id, household_id, piece_id, kind, title, body, version, place_order, "
              "place_size, changed_by, outside) VALUES (%s, %s, %s, 'measurements', 'm', %s, 1, %s, 'small', 1, %s) RETURNING 1")
    scalar(url, insert, (bench, home, 1, body, 0, False))
    scalar(url, insert, (bench, home, 2, OUTSIDE_ASKED, 1, True))
    edit = {"type": "edit", "piece_id": 1, "base_version": 1, "title": "m", "body": body}
    effect = {"type": "edited", "piece_id": 1, "before": {"title": "m", "body": body}, "after": {"title": "m", "body": body}}
    scalar(url, "INSERT INTO bench_commands (bench_id, household_id, seq, command, outcome, effect) "
                "VALUES (%s, %s, 2, %s::jsonb, 'accepted', %s::jsonb) RETURNING 1",
           (bench, home, json.dumps(edit), json.dumps(effect)))
    return bench, home


def migrated(url: str) -> tuple[int, int]:
    this, before = revision_named("asked_numbers_surfaced")
    command.upgrade(alembic_config(url), before)
    bench, home = seed(url)
    command.upgrade(alembic_config(url), this)
    return bench, home


def test_an_asked_guessed_number_becomes_a_surfaced_naming_it_as_shown(empty_database: str) -> None:
    bench, _ = migrated(empty_database)
    with psycopg.connect(empty_database) as conn:
        rows = conn.execute("SELECT seq, person_id, command, effect FROM bench_commands WHERE bench_id = %s "
                            "AND command->>'type' = 'surfaced'", (bench,)).fetchall()
        next_seq = conn.execute("SELECT next_seq FROM benches WHERE id = %s", (bench,)).fetchone()
    assert len(rows) == 1
    seq, person, raw_command, raw_effect = rows[0]
    assert (seq, person, next_seq) == (3, None, (4,))
    assert decode_command(raw_command, By(None)) == Surfaced(By(None), 1, (ShownRow("strap_width", "15 mm"),))
    assert decode_effect(raw_effect) == Shown(1, (ShownRow("strap_width", "15 mm"),))


def test_the_key_leaves_every_stored_body_and_nothing_else_changes(empty_database: str) -> None:
    bench, _ = migrated(empty_database)
    with psycopg.connect(empty_database) as conn:
        bodies = [r[0] for r in conn.execute("SELECT body FROM bench_pieces WHERE bench_id = %s ORDER BY piece_id", (bench,))]
        logged = conn.execute("SELECT command::text, effect::text FROM bench_commands WHERE seq = 2").fetchone()
    assert logged is not None
    assert all("asked" not in text for text in [*bodies, *logged])
    assert json.loads(bodies[0]) == {"items": [
        {"name": "strap_width", "value": 15.0, "unit": "mm", "source": "guessed"},
        {"name": "rim", "value": 2.5, "unit": "mm", "source": "guessed"},
        {"name": "hole", "value": 6, "unit": "mm", "source": "measured"},
        {"kind": "choice", "name": "form", "label": "The strap", "value": "flat", "source": "guessed"}]}


def test_an_outside_piece_is_cleaned_but_nothing_of_it_is_shown(empty_database: str) -> None:
    bench, _ = migrated(empty_database)
    shown = scalar(empty_database, "SELECT count(*) FROM bench_commands WHERE bench_id = %s AND "
                                   "effect::text LIKE '%%\"x\"%%' AND command->>'type' = 'surfaced'", (bench,))
    assert shown == 0
    assert "asked" not in scalar(empty_database, "SELECT body FROM bench_pieces WHERE bench_id = %s AND piece_id = 2", (bench,))
