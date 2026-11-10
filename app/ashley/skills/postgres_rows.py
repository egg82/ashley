"""The skills' SQL, one statement per function, each on a connection the caller holds in its transaction. Tables
`skill_versions` (the changelog, append-only apart from a proposal's status) and `skill_pins`."""

from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from .skills import Status, Version

Conn = AsyncConnection[tuple[Any, ...]]
_VERSION = "version, status, body, what, why, base_version, restored_from, bench_id, person_id, at"


def _version(row: tuple[Any, ...]) -> Version:
    return Version(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9].astimezone(UTC))


async def lock(conn: Conn, household_id: int, kind: str) -> None:
    """Held to the end of the transaction: changes to one household's kind are decided one after the other."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"skill:{household_id}:{kind}",))


async def head(conn: Conn, household_id: int, kind: str) -> tuple[int, str, datetime] | None:
    """The latest live version's number, body and time."""
    cur = await conn.execute(
        "SELECT version, body, at FROM skill_versions WHERE household_id = %s AND kind = %s AND status = 'live' "
        "ORDER BY version DESC LIMIT 1", (household_id, kind))
    row = await cur.fetchone()
    return None if row is None else (int(row[0]), row[1], row[2].astimezone(UTC))


async def live_body(conn: Conn, household_id: int, kind: str, version: int) -> str | None:
    cur = await conn.execute(
        "SELECT body FROM skill_versions WHERE household_id = %s AND kind = %s AND version = %s AND status = 'live'",
        (household_id, kind, version))
    row = await cur.fetchone()
    return None if row is None else row[0]


async def live_count(conn: Conn, household_id: int, kind: str) -> int:
    cur = await conn.execute(
        "SELECT count(*) FROM skill_versions WHERE household_id = %s AND kind = %s AND status = 'live'",
        (household_id, kind))
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def next_version(conn: Conn, household_id: int, kind: str) -> int:
    cur = await conn.execute(
        "SELECT coalesce(max(version), 0) + 1 FROM skill_versions WHERE household_id = %s AND kind = %s",
        (household_id, kind))
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def insert(conn: Conn, household_id: int, kind: str, version: int, body: str, what: str, why: str,
                 status: Status, base_version: int, restored_from: int | None, bench_id: int | None,
                 person_id: int | None) -> None:
    await conn.execute(
        "INSERT INTO skill_versions (household_id, kind, version, body, what, why, status, base_version, "
        "restored_from, bench_id, person_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (household_id, kind, version, body, what, why, status, base_version, restored_from, bench_id, person_id))


async def is_pinned(conn: Conn, household_id: int, kind: str) -> bool:
    cur = await conn.execute("SELECT 1 FROM skill_pins WHERE household_id = %s AND kind = %s", (household_id, kind))
    return await cur.fetchone() is not None


async def set_pinned(conn: Conn, household_id: int, kind: str, pinned: bool) -> None:
    if pinned:
        await conn.execute("INSERT INTO skill_pins (household_id, kind) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                           (household_id, kind))
    else:
        await conn.execute("DELETE FROM skill_pins WHERE household_id = %s AND kind = %s", (household_id, kind))


async def proposal(conn: Conn, household_id: int, kind: str) -> Version | None:
    """The newest proposal still waiting."""
    cur = await conn.execute(
        f"SELECT {_VERSION} FROM skill_versions WHERE household_id = %s AND kind = %s AND status = 'proposed' "
        "ORDER BY version DESC LIMIT 1", (household_id, kind))
    row = await cur.fetchone()
    return None if row is None else _version(row)


async def changelog(conn: Conn, household_id: int, kind: str, limit: int) -> tuple[Version, ...]:
    cur = await conn.execute(
        f"SELECT {_VERSION} FROM skill_versions WHERE household_id = %s AND kind = %s ORDER BY version DESC LIMIT %s",
        (household_id, kind, limit))
    return tuple(_version(r) for r in await cur.fetchall())


async def waiting(conn: Conn, household_id: int, kind: str, version: int) -> Version | None:
    """The version when it is a proposal still waiting."""
    cur = await conn.execute(
        f"SELECT {_VERSION} FROM skill_versions WHERE household_id = %s AND kind = %s AND version = %s "
        "AND status = 'proposed'", (household_id, kind, version))
    row = await cur.fetchone()
    return None if row is None else _version(row)


async def set_status(conn: Conn, household_id: int, kind: str, version: int, status: Status) -> None:
    await conn.execute("UPDATE skill_versions SET status = %s, at = now() WHERE household_id = %s AND kind = %s AND version = %s",
                       (status, household_id, kind, version))


async def kinds(conn: Conn, household_id: int) -> dict[str, str]:
    """The household's own kinds by slug, with their labels."""
    cur = await conn.execute("SELECT kind, label FROM skill_kinds WHERE household_id = %s ORDER BY kind", (household_id,))
    return {r[0]: r[1] for r in await cur.fetchall()}


async def insert_kind(conn: Conn, household_id: int, kind: str, label: str) -> bool:
    """Starts the kind; False when the household already has it."""
    cur = await conn.execute(
        "INSERT INTO skill_kinds (household_id, kind, label) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (household_id, kind, label))
    return cur.rowcount == 1
