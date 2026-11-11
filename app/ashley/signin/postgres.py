"""Sessions in Postgres: tables `signin_pending`, `sessions`, `signin_unmapped` and `link_pending`. Every time is the database's own
`now()`, so pods on two sites agree on what has expired. One transaction per call."""

import hashlib
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import psycopg

from ..db.database import Database, DatabaseUnavailable
from ..people.model import Person
from .model import LinkPending, Opened, Pending, SignedIn
from .policy import Policy
from .sessions import Sessions, SessionsUnavailable

_FIND = (
    "SELECT s.id, p.id, p.household_id, p.name, s.last_seen_at < now() - make_interval(mins => %(touch)s) "
    "FROM sessions s JOIN accounts a ON a.id = s.account_id "
    "JOIN people p ON p.id = a.person_id AND p.household_id = a.household_id "
    "WHERE s.token_sha256 = %(hash)s AND s.expires_at > now() AND s.last_seen_at > now() - make_interval(days => %(idle)s)"
)
_CLOSE = (
    "WITH gone AS (DELETE FROM sessions WHERE token_sha256 = %s RETURNING id, account_id) "
    "SELECT g.id, p.id, p.household_id, p.name FROM gone g JOIN accounts a ON a.id = g.account_id "
    "JOIN people p ON p.id = a.person_id AND p.household_id = a.household_id"
)


def sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


class PostgresSessions(Sessions):
    def __init__(self, database: Database, policy: Policy) -> None:
        self._database = database
        self._policy = policy

    @asynccontextmanager
    async def _conn(self) -> AsyncGenerator[psycopg.AsyncConnection[tuple[Any, ...]]]:
        try:
            async with self._database.connection() as conn:
                yield conn
        except DatabaseUnavailable as e:
            raise SessionsUnavailable("no database connection") from e
        except psycopg.OperationalError as e:
            raise SessionsUnavailable("database unreachable") from e

    async def begin(self, state: str, pending: Pending) -> bool:
        async with self._conn() as conn:
            await conn.execute("DELETE FROM signin_pending WHERE created_at < now() - make_interval(mins => %s)",
                               (self._policy.pending_minutes,))
            await conn.execute("LOCK TABLE signin_pending IN SHARE ROW EXCLUSIVE MODE")
            cur = await conn.execute(
                "INSERT INTO signin_pending (state_sha256, verifier, nonce, next) "
                "SELECT %s, %s, %s, %s WHERE (SELECT count(*) FROM signin_pending) < %s",
                (sha256(state), pending.verifier, pending.nonce, pending.next, self._policy.max_pending))
            return cur.rowcount == 1

    async def take(self, state: str) -> Pending | None:
        async with self._conn() as conn:
            cur = await conn.execute(
                "DELETE FROM signin_pending WHERE state_sha256 = %s RETURNING verifier, nonce, next, "
                "created_at >= now() - make_interval(mins => %s)", (sha256(state), self._policy.pending_minutes))
            row = await cur.fetchone()
        return None if row is None or not row[3] else Pending(row[0], row[1], row[2])

    async def open(self, system: str, external_id: str, admin_group: bool | None = None) -> Opened | None:
        token = secrets.token_urlsafe(32)
        async with self._conn() as conn:
            await conn.execute("DELETE FROM sessions WHERE expires_at <= now() "
                               "OR last_seen_at <= now() - make_interval(days => %s)", (self._policy.idle_days,))
            cur = await conn.execute(
                "WITH made AS (INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                "SELECT %s, a.id, a.household_id, now() + make_interval(days => %s) FROM accounts a "
                "WHERE a.system = %s AND a.external_id = %s RETURNING id, account_id) "
                "SELECT m.id, p.id, p.household_id, p.name FROM made m JOIN accounts a ON a.id = m.account_id "
                "JOIN people p ON p.id = a.person_id AND p.household_id = a.household_id",
                (sha256(token), self._policy.session_days, system, external_id))
            row = await cur.fetchone()
        return None if row is None else Opened(token, SignedIn(row[0], Person(row[1], row[2], row[3])))

    async def find(self, token: str) -> SignedIn | None:
        if not token:
            return None
        async with self._conn() as conn:
            cur = await conn.execute(_FIND, {"hash": sha256(token), "touch": self._policy.touch_minutes,
                                             "idle": self._policy.idle_days})
            row = await cur.fetchone()
            if row is not None and row[4]:
                await conn.execute("UPDATE sessions SET last_seen_at = now() WHERE id = %s", (row[0],))
        return None if row is None else SignedIn(row[0], Person(row[1], row[2], row[3]))

    async def close(self, token: str) -> SignedIn | None:
        if not token:
            return None
        async with self._conn() as conn:
            row = await (await conn.execute(_CLOSE, (sha256(token),))).fetchone()
        return None if row is None else SignedIn(row[0], Person(row[1], row[2], row[3]))

    async def refused(self, system: str, external_id: str, username: str) -> None:
        async with self._conn() as conn:
            await conn.execute("DELETE FROM signin_unmapped WHERE last_seen_at < now() - make_interval(days => %s)",
                               (self._policy.unmapped_retention_days,))
            await conn.execute(
                "INSERT INTO signin_unmapped (system, external_id, username) VALUES (%s, %s, %s) "
                "ON CONFLICT (system, external_id) DO UPDATE SET username = excluded.username, last_seen_at = now()",
                (system, external_id, username))

    async def begin_link(self, state: str, pending: LinkPending) -> bool:
        async with self._conn() as conn:
            await conn.execute("DELETE FROM link_pending WHERE created_at < now() - make_interval(mins => %s)",
                               (self._policy.pending_minutes,))
            await conn.execute("LOCK TABLE link_pending IN SHARE ROW EXCLUSIVE MODE")
            cur = await conn.execute(
                "INSERT INTO link_pending (state_sha256, household_id, person_id, verifier) "
                "SELECT %s, %s, %s, %s WHERE (SELECT count(*) FROM link_pending) < %s",
                (sha256(state), pending.household_id, pending.person_id, pending.verifier, self._policy.max_pending))
            return cur.rowcount == 1

    async def take_link(self, state: str) -> LinkPending | None:
        async with self._conn() as conn:
            cur = await conn.execute(
                "DELETE FROM link_pending WHERE state_sha256 = %s RETURNING household_id, person_id, verifier, "
                "created_at >= now() - make_interval(mins => %s)", (sha256(state), self._policy.pending_minutes))
            row = await cur.fetchone()
        return None if row is None or not row[3] else LinkPending(row[0], row[1], row[2])
