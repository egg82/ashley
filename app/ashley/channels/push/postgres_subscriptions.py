"""Subscriptions in Postgres, table `push_subscriptions`, one row per endpoint."""

from typing import LiteralString

import psycopg

from ...db.database import Database, DatabaseUnavailable
from .subscriptions import Browser, Subscription, Subscriptions, SubscriptionsUnavailable

_DOWN = (DatabaseUnavailable, psycopg.Error)


class PostgresSubscriptions(Subscriptions):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def add(self, household_id: int, person_id: int, browser: Browser) -> None:
        await self._execute(
            "INSERT INTO push_subscriptions (household_id, person_id, endpoint, p256dh, auth) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (endpoint) DO UPDATE SET household_id = excluded.household_id, "
            "person_id = excluded.person_id, p256dh = excluded.p256dh, auth = excluded.auth",
            (household_id, person_id, browser.endpoint, browser.p256dh, browser.auth))

    async def remove(self, person_id: int, endpoint: str) -> None:
        await self._execute("DELETE FROM push_subscriptions WHERE person_id = %s AND endpoint = %s",
                            (person_id, endpoint))

    async def count(self, person_id: int, endpoint: str | None = None) -> tuple[int, bool]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT count(*), coalesce(bool_or(endpoint = %s), false) FROM push_subscriptions "
                    "WHERE person_id = %s", (endpoint, person_id))
                row = await cur.fetchone()
        except _DOWN as e:
            raise SubscriptionsUnavailable("database unreachable") from e
        assert row is not None
        return int(row[0]), bool(row[1])

    async def of(self, household_id: int, person_id: int) -> tuple[Subscription, ...]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
                    "WHERE household_id = %s AND person_id = %s ORDER BY id", (household_id, person_id))
                rows = await cur.fetchall()
        except _DOWN as e:
            raise SubscriptionsUnavailable("database unreachable") from e
        return tuple(Subscription(r[0], household_id, person_id, Browser(r[1], r[2], r[3])) for r in rows)

    async def delivered(self, subscription_id: int) -> None:
        await self._execute("UPDATE push_subscriptions SET last_success_at = now() WHERE id = %s", (subscription_id,))

    async def gone(self, subscription_id: int) -> None:
        await self._execute("DELETE FROM push_subscriptions WHERE id = %s", (subscription_id,))

    async def _execute(self, query: LiteralString, params: tuple[object, ...]) -> None:
        try:
            async with self._database.connection() as conn:
                await conn.execute(query, params)
        except _DOWN as e:
            raise SubscriptionsUnavailable("database unreachable") from e
