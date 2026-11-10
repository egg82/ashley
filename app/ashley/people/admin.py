"""The writes behind `python -m ashley.people`: plain SQL on a connection the caller owns and commits. People are
written only here; the `People` service reads."""

import psycopg

from .fields import is_timezone


class NotFound(Exception):
    """The household or person a write names does not exist."""


def _one(cur: psycopg.Cursor[tuple[int]]) -> int:
    row = cur.fetchone()
    if row is None:
        raise NotFound()
    return row[0]


def add_household(conn: psycopg.Connection, name: str, timezone: str) -> int:
    """Raises ValueError when `timezone` is not an IANA zone name."""
    if not is_timezone(timezone):
        raise ValueError(f"not an IANA timezone: {timezone!r}")
    return _one(conn.execute("INSERT INTO households (name, timezone) VALUES (%s, %s) RETURNING id", (name, timezone)))


def set_profile(conn: psycopg.Connection, household_id: int, profile: str) -> None:
    _one(conn.execute("UPDATE households SET profile = %s WHERE id = %s RETURNING id", (profile, household_id)))


def add_person(conn: psycopg.Connection, household_id: int, name: str) -> int:
    if not name.strip():
        raise ValueError("a person has a name")
    return _one(conn.execute(
        "INSERT INTO people (household_id, name) SELECT id, %s FROM households WHERE id = %s RETURNING id",
        (name, household_id)))


def add_account(conn: psycopg.Connection, person_id: int, system: str, external_id: str) -> int:
    """The account joins its person's household. Raises psycopg's IntegrityError for a malformed `system`, a blank
    `external_id` or one already mapped."""
    return _one(conn.execute(
        "INSERT INTO accounts (household_id, person_id, system, external_id) "
        "SELECT household_id, id, %s, %s FROM people WHERE id = %s RETURNING id",
        (system, external_id, person_id)))


def listing(conn: psycopg.Connection, household_id: int) -> list[tuple[int, str, str | None, str | None]]:
    """Each person with each of their accounts (id, name, system, external id); a person with none appears once with
    None for both."""
    rows = conn.execute(
        "SELECT p.id, p.name, a.system, a.external_id FROM people p LEFT JOIN accounts a "
        "ON a.person_id = p.id AND a.household_id = p.household_id "
        "WHERE p.household_id = %s ORDER BY p.id, a.id", (household_id,)).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]
