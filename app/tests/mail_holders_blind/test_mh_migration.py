"""The `connection_resources` migration: its constraints, and the `person_id` check that moved to the service."""

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from ashley.db.migrate import alembic_config
from contract.conversations_support import scalar

INSERT = ("INSERT INTO connection_resources (household_id, connection_id, ref, kind, name, shared) "
          "VALUES (%s, %s, %s, %s, %s, %s)")


def revision_named(name: str) -> tuple[str, str]:
    script = ScriptDirectory.from_config(alembic_config(""))
    [found] = [r for r in script.walk_revisions() if r.path.endswith(f"_{name}.py")]
    assert isinstance(found.down_revision, str)
    return found.revision, found.down_revision


def connection(url: str, kind: str = "google", label: str = "", person: bool = False) -> int:
    home = int(scalar(url, "INSERT INTO households (name) VALUES (%s) RETURNING id", (f"h{label}{kind}",)))
    who = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'A') RETURNING id", (home,)))
    return int(scalar(url, "INSERT INTO connections (household_id, kind, label, base_url, secret, person_id) "
                           "VALUES (%s, %s, %s, 'https://x.test', '\\x00', %s) RETURNING id",
                      (home, kind, label, who if person else None)))


def put(url: str, cid: int, ref: str = "a@x.test", kind: str = "mailbox", name: str = "n",
        shared: bool | None = False) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        found = conn.execute("SELECT household_id FROM connections WHERE id = %s", (cid,)).fetchall()
    home = found[0][0] if found else scalar(url, "INSERT INTO households (name) VALUES ('nobody') RETURNING id")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(INSERT.encode(), (home, cid, ref, kind, name, shared))


def test_the_table_has_the_columns_the_design_names(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        got = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns "
                                          "WHERE table_name = 'connection_resources'").fetchall()}
    assert {"connection_id", "ref", "kind", "name", "shared"} <= got


def test_a_row_is_stored_as_given(db_url: str) -> None:
    cid = connection(db_url)
    put(db_url, cid, "x@y.test", "mailbox", "The name", True)
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT ref, kind, name, shared FROM connection_resources WHERE connection_id = %s",
                            (cid,)).fetchall() == [("x@y.test", "mailbox", "The name", True)]


def test_deleting_the_connection_deletes_its_resources(db_url: str) -> None:
    cid, other = connection(db_url), connection(db_url, label="2")
    put(db_url, cid)
    put(db_url, other)
    scalar(db_url, "DELETE FROM connections WHERE id = %s RETURNING 1", (cid,))
    assert int(scalar(db_url, "SELECT count(*) FROM connection_resources WHERE connection_id = %s", (cid,))) == 0
    assert int(scalar(db_url, "SELECT count(*) FROM connection_resources WHERE connection_id = %s", (other,))) == 1


@pytest.mark.parametrize("length", [1, 200])
def test_a_ref_of_one_to_two_hundred_characters_is_accepted(db_url: str, length: int) -> None:
    put(db_url, connection(db_url), "r" * length)


@pytest.mark.parametrize("ref", ["", "r" * 201])
def test_a_ref_outside_one_to_two_hundred_characters_is_refused(db_url: str, ref: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        put(db_url, connection(db_url), ref)


def test_a_ref_is_unique_within_its_connection(db_url: str) -> None:
    cid = connection(db_url)
    put(db_url, cid)
    with pytest.raises(psycopg.errors.UniqueViolation):
        put(db_url, cid, name="again", shared=True)


def test_the_same_ref_may_belong_to_two_connections(db_url: str) -> None:
    put(db_url, connection(db_url))
    put(db_url, connection(db_url, label="2"))


def test_a_different_ref_may_share_a_connection(db_url: str) -> None:
    cid = connection(db_url)
    put(db_url, cid, "a@x.test")
    put(db_url, cid, "b@x.test")


def test_a_resource_needs_a_connection(db_url: str) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        put(db_url, 987654)


def test_shared_is_never_null(db_url: str) -> None:
    with pytest.raises(psycopg.errors.NotNullViolation):
        put(db_url, connection(db_url), shared=None)


def test_the_person_check_that_personal_implied_is_gone(db_url: str) -> None:
    connection(db_url, kind="gitlab", person=False)
    connection(db_url, kind="google", label="p", person=True)


def test_the_migration_keeps_the_connections_it_finds(empty_database: str) -> None:
    url = empty_database
    this, before = revision_named("connection_resources")
    command.upgrade(alembic_config(url), before)
    home = int(scalar(url, "INSERT INTO households (name) VALUES ('Willow') RETURNING id"))
    cid = int(scalar(url, "INSERT INTO connections (household_id, kind, label, base_url, secret) "
                          "VALUES (%s, 'sure', '', 'https://x.test', '\\x00') RETURNING id", (home,)))
    command.upgrade(alembic_config(url), this)
    assert int(scalar(url, "SELECT count(*) FROM connections WHERE id = %s", (cid,))) == 1
    put(url, cid)
    command.downgrade(alembic_config(url), before)
    assert int(scalar(url, "SELECT count(*) FROM connections WHERE id = %s", (cid,))) == 1
