"""The persona overrides' SQL: the `persona` family of `skill_versions`, a section id in `kind`. One statement per
function, each on a connection the caller holds in its transaction."""

from datetime import UTC
from typing import Any

from .persona import PersonaVersion
from .postgres_rows import Conn

_VERSION = "version, body, what, why, base_version, restored_from, person_id, at"


def _version(row: tuple[Any, ...]) -> PersonaVersion:
    return PersonaVersion(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7].astimezone(UTC))


async def lock(conn: Conn, household_id: int, section: str) -> None:
    """Held to the end of the transaction: changes to one household's section are decided one after the other."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"persona:{household_id}:{section}",))


async def heads(conn: Conn, household_id: int) -> dict[str, PersonaVersion]:
    """Each section's newest version."""
    cur = await conn.execute(
        f"SELECT DISTINCT ON (kind) kind, {_VERSION} FROM skill_versions WHERE household_id = %s AND family = 'persona' "
        "ORDER BY kind, version DESC", (household_id,))
    return {r[0]: _version(r[1:]) for r in await cur.fetchall()}


async def head(conn: Conn, household_id: int, section: str) -> PersonaVersion | None:
    cur = await conn.execute(
        f"SELECT {_VERSION} FROM skill_versions WHERE household_id = %s AND family = 'persona' AND kind = %s "
        "ORDER BY version DESC LIMIT 1", (household_id, section))
    row = await cur.fetchone()
    return None if row is None else _version(row)


async def body_of(conn: Conn, household_id: int, section: str, version: int) -> tuple[bool, str | None]:
    """Whether `version` exists, and its body."""
    cur = await conn.execute(
        "SELECT body FROM skill_versions WHERE household_id = %s AND family = 'persona' AND kind = %s AND version = %s",
        (household_id, section, version))
    row = await cur.fetchone()
    return (False, None) if row is None else (True, row[0])


async def insert(conn: Conn, household_id: int, section: str, version: int, body: str | None, what: str, why: str,
                 base_version: int, restored_from: int | None, person_id: int) -> None:
    await conn.execute(
        "INSERT INTO skill_versions (household_id, family, kind, version, body, what, why, status, base_version, "
        "restored_from, person_id) VALUES (%s, 'persona', %s, %s, %s, %s, %s, 'live', %s, %s, %s)",
        (household_id, section, version, body, what, why, base_version, restored_from, person_id))


async def changelog(conn: Conn, household_id: int, section: str, limit: int) -> tuple[PersonaVersion, ...]:
    cur = await conn.execute(
        f"SELECT {_VERSION} FROM skill_versions WHERE household_id = %s AND family = 'persona' AND kind = %s "
        "ORDER BY version DESC LIMIT %s", (household_id, section, limit))
    return tuple(_version(r) for r in await cur.fetchall())
