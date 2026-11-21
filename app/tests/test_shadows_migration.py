"""The shadow-run migration, found by its name so a renumber changes nothing: installs from before it are real ones,
its tables take a run and its firings (a firing goes with its run), and downgrading drops them with the shadow installs
and keeps every real install."""

from datetime import UTC, datetime

import psycopg
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def revision_named(name: str) -> tuple[str, str]:
    script = ScriptDirectory.from_config(alembic_config(""))
    [found] = [r for r in script.walk_revisions() if r.path.endswith(f"_{name}.py")]
    assert isinstance(found.down_revision, str)
    return found.revision, found.down_revision


def seeded(url: str) -> tuple[int, int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    alana = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,)))
    bench = int(scalar(url, "INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, 'b') RETURNING id", (home, alana)))
    with psycopg.connect(url, autocommit=True) as conn:
        for seq in (1, 2):
            conn.execute("INSERT INTO bench_commands (bench_id, household_id, seq, person_id, command, outcome, effect) "
                         "VALUES (%s, %s, %s, %s, '{}', 'accepted', '{}')", (bench, home, seq, alana))
            conn.execute("INSERT INTO bench_installs (bench_id, household_id, seq, piece_id, action, automation_id, touched) "
                         "VALUES (%s, %s, %s, 1, 'install', 'a', true)", (bench, home, seq))
    return home, alana, bench


def test_installs_from_before_are_real_and_a_firing_goes_with_its_run(empty_database: str) -> None:
    this, before = revision_named("automation_shadows")
    command.upgrade(alembic_config(empty_database), before)
    home, alana, bench = seeded(empty_database)
    command.upgrade(alembic_config(empty_database), this)
    assert scalar(empty_database, "SELECT count(*) FROM bench_installs WHERE NOT shadow") == 2
    with psycopg.connect(empty_database, autocommit=True) as conn:
        conn.execute("INSERT INTO automation_shadows (bench_id, install_seq, household_id, piece_id, version, person_id, "
                     "started_at, ends_at) VALUES (%s, 2, %s, 1, 1, %s, %s, %s)", (bench, home, alana, NOW, NOW.replace(hour=13)))
        conn.execute("INSERT INTO automation_shadow_firings (household_id, bench_id, install_seq, kind, fired_at, context) "
                     "VALUES (%s, %s, 2, 'would', %s, 'c')", (home, bench, NOW))
        conn.execute("DELETE FROM automation_shadows")
    assert scalar(empty_database, "SELECT count(*) FROM automation_shadow_firings") == 0


def test_downgrading_drops_the_tables_and_the_shadow_installs_and_keeps_the_real_ones(empty_database: str) -> None:
    this, before = revision_named("automation_shadows")
    command.upgrade(alembic_config(empty_database), this)
    seeded(empty_database)
    with psycopg.connect(empty_database, autocommit=True) as conn:
        conn.execute("UPDATE bench_installs SET shadow = true WHERE seq = 2")
    command.downgrade(alembic_config(empty_database), before)
    assert [scalar(empty_database, f"SELECT to_regclass('{t}')::text") for t in ("automation_shadows", "automation_shadow_firings")] == [None, None]
    assert scalar(empty_database, "SELECT array_agg(seq) FROM bench_installs") == [1]
    assert scalar(empty_database, "SELECT count(*) FROM information_schema.columns "
                                  "WHERE table_name = 'bench_installs' AND column_name = 'shadow'") == 0
