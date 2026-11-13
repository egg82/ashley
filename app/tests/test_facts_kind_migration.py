"""The migration that renames the piece kind `measurements` to `facts`, with a row before and after: the pieces' kind, the
`kind` of a stored Add and of the piece an effect carries, the refusal of a stored outcome and the file a run left, and
nothing else that merely says the word."""

import json

import psycopg
from alembic import command
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar
from test_proposals_migration import revision_named

BODY = json.dumps({"items": [{"name": "hole", "value": 6, "unit": "mm", "source": "measured"},
                             {"kind": "choice", "name": "form", "label": "Form", "value": "flat", "source": "guessed"}]})
PLACE = {"order": 0, "size": "small"}


def piece(kind: str, body: str = BODY) -> dict[str, object]:
    return {"id": 1, "kind": kind, "title": "m", "body": body, "version": 1, "place": PLACE, "changed_by": 1}


def seed(url: str) -> tuple[int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    bench = int(scalar(url, "INSERT INTO benches (household_id, owner_id, title, next_seq) VALUES (%s, %s, 'Strap', 5) "
                       "RETURNING id", (home, alana)))
    insert = ("INSERT INTO bench_pieces (bench_id, household_id, piece_id, kind, title, body, version, place_order, "
              "place_size, changed_by, outside) VALUES (%s, %s, %s, %s, 'm', %s, 1, %s, 'small', 1, false) RETURNING 1")
    scalar(url, insert, (bench, home, 1, "measurements", BODY, 0))
    scalar(url, insert, (bench, home, 2, "note", "the measurements are in piece 1", 1))
    log = ("INSERT INTO bench_commands (bench_id, household_id, seq, command, outcome, effect) "
           "VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb) RETURNING 1")
    add = {"type": "add", "kind": "measurements", "title": "m", "body": BODY, "size": "small"}
    added = {"type": "added", "piece": piece("measurements")}
    scalar(url, log, (bench, home, 1, json.dumps(add), "accepted", json.dumps(added)))
    scalar(url, log, (bench, home, 2, json.dumps({**add, "kind": "note", "body": "measurements"}), "accepted",
                      json.dumps({"type": "added", "piece": piece("note", "measurements")})))
    scalar(url, "INSERT INTO bench_commands (bench_id, household_id, seq, command, outcome) "
                "VALUES (%s, %s, 3, %s::jsonb, 'bad_measurements') RETURNING 1",
           (bench, home, json.dumps({**add, "body": "x"})))
    scalar(url, "INSERT INTO bench_commands (bench_id, household_id, seq, command, outcome) "
                "VALUES (%s, %s, 4, %s::jsonb, 'stale_base') RETURNING 1",
           (bench, home, json.dumps({"type": "edit", "piece_id": 1, "base_version": 0, "title": "m", "body": "measurements"})))
    files = json.dumps({"model.py": "x", "measurements.json": BODY, "print.json": "{}"})
    scalar(url, "INSERT INTO code_runs (household_id, language, script, stdin, files, out_files, bench_id, bench_seq, "
                "piece_id, piece_version) VALUES (%s, 'build123d', 's', '', %s::jsonb, %s::jsonb, %s, 1, 1, 1) "
                "RETURNING id", (home, files, files, bench))
    return bench, home


def migrated(url: str) -> int:
    this, before = revision_named("facts_kind")
    command.upgrade(alembic_config(url), before)
    bench, _ = seed(url)
    command.upgrade(alembic_config(url), this)
    return bench


def test_the_kind_is_facts_in_the_pieces_and_in_every_command_and_effect_that_names_it(empty_database: str) -> None:
    bench = migrated(empty_database)
    with psycopg.connect(empty_database) as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM bench_pieces WHERE bench_id = %s ORDER BY piece_id", (bench,))]
        logged = conn.execute("SELECT seq, command, effect, outcome FROM bench_commands WHERE bench_id = %s ORDER BY seq",
                              (bench,)).fetchall()
    assert kinds == ["facts", "note"]
    assert logged[0][1]["kind"] == "facts" and logged[0][2]["piece"]["kind"] == "facts"
    assert logged[2][1]["kind"] == "facts" and logged[2][3] == "bad_facts"
    assert logged[0][1]["body"] == BODY and logged[0][2]["piece"]["body"] == BODY


def test_nothing_that_only_says_the_word_changes(empty_database: str) -> None:
    bench = migrated(empty_database)
    with psycopg.connect(empty_database) as conn:
        note = conn.execute("SELECT body FROM bench_pieces WHERE bench_id = %s AND piece_id = 2", (bench,)).fetchone()
        logged = conn.execute("SELECT command, effect, outcome FROM bench_commands WHERE bench_id = %s AND seq IN (2, 4) "
                              "ORDER BY seq", (bench,)).fetchall()
    assert note == ("the measurements are in piece 1",)
    assert logged[0][0] == {"type": "add", "kind": "note", "title": "m", "body": "measurements", "size": "small"}
    assert logged[0][1]["piece"] == piece("note", "measurements")
    assert logged[1][0]["body"] == "measurements" and logged[1][2] == "stale_base"


def test_the_file_a_run_left_is_named_facts_json_and_its_inputs_stay_as_they_ran(empty_database: str) -> None:
    migrated(empty_database)
    with psycopg.connect(empty_database) as conn:
        left, ran = conn.execute("SELECT out_files, files FROM code_runs").fetchone() or ({}, {})
    assert left == {"model.py": "x", "facts.json": BODY, "print.json": "{}"}
    assert ran == {"model.py": "x", "measurements.json": BODY, "print.json": "{}"}


def test_the_downgrade_puts_every_name_back(empty_database: str) -> None:
    this, before = revision_named("facts_kind")
    migrated(empty_database)
    command.downgrade(alembic_config(empty_database), before)
    with psycopg.connect(empty_database) as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM bench_pieces ORDER BY piece_id")]
        outcomes = [r[0] for r in conn.execute("SELECT outcome FROM bench_commands ORDER BY seq")]
        left = conn.execute("SELECT out_files FROM code_runs").fetchone()
    assert (kinds, outcomes[2]) == (["measurements", "note"], "bad_measurements")
    assert left is not None and set(left[0]) == {"model.py", "measurements.json", "print.json"}
    assert this == "0122"
