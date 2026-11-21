"""Open screens in Postgres, table `live_screens`."""

from datetime import datetime
from typing import Any, Literal, LiteralString

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .screens import OpenScreen, ScreenFeed, Screens, ScreensUnavailable

LEFT_BEHIND_S = 86400
"""How long a row survives with no heartbeat before the next opening in its household removes it."""


class PostgresScreens(Screens):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def opened(self, household_id: int, person_id: int, token: str | None = None) -> int:
        await self._prune(household_id)
        return await self._insert("person_id", household_id, person_id, token)

    async def device_opened(self, household_id: int, device_id: int, token: str | None = None) -> int:
        await self._prune(household_id)
        return await self._insert("device_id", household_id, device_id, token)

    async def person_visible(self, person_id: int, token: str, visible: bool) -> None:
        await self._run("UPDATE live_screens SET visible = %s WHERE person_id = %s AND token = %s::uuid",
                        (visible, person_id, token))

    async def device_visible(self, device_id: int, token: str, visible: bool) -> None:
        await self._run("UPDATE live_screens SET visible = %s WHERE device_id = %s AND token = %s::uuid",
                        (visible, device_id, token))

    async def open_screens(self, household_id: int, within_s: float) -> tuple[OpenScreen, ...]:
        rows = await self._run("SELECT person_id, device_id, visible FROM live_screens WHERE household_id = %s "
                               "AND seen_at > now() - make_interval(secs => %s) ORDER BY id", (household_id, within_s))
        return tuple(OpenScreen(row[0], row[1], row[2]) for row in rows)

    async def show_feed(self, household_id: int, camera_id: str, until: datetime, people: tuple[int, ...],
                        devices: tuple[int, ...], within_s: float) -> int:
        shown = await self._run(
            "UPDATE live_screens SET feed_camera = %s, feed_until = %s WHERE household_id = %s AND visible "
            "AND seen_at > now() - make_interval(secs => %s) AND (person_id = ANY(%s) OR device_id = ANY(%s)) "
            "RETURNING id", (camera_id, until, household_id, within_s, list(people), list(devices)))
        return len(shown)

    async def feed_of(self, token: str, now: datetime, person_id: int | None = None,
                      device_id: int | None = None) -> ScreenFeed | None:
        found = await self._run(
            "SELECT feed_camera, feed_until FROM live_screens WHERE token = %s::uuid AND (person_id = %s "
            "OR device_id = %s) AND feed_camera IS NOT NULL AND feed_until > %s", (token, person_id, device_id, now))
        return ScreenFeed(found[0][0], found[0][1]) if found else None

    async def dismiss_feed(self, token: str, person_id: int | None = None, device_id: int | None = None) -> None:
        await self._run("UPDATE live_screens SET feed_camera = NULL, feed_until = NULL WHERE token = %s::uuid "
                        "AND (person_id = %s OR device_id = %s)", (token, person_id, device_id))

    async def clear_feed(self, household_id: int) -> int:
        cleared = await self._run("UPDATE live_screens SET feed_camera = NULL, feed_until = NULL WHERE household_id = %s "
                                  "AND feed_camera IS NOT NULL RETURNING id", (household_id,))
        return len(cleared)

    async def beat(self, screen_id: int) -> None:
        await self._run("UPDATE live_screens SET seen_at = now() WHERE id = %s", (screen_id,))

    async def closed(self, screen_id: int) -> None:
        await self._run("DELETE FROM live_screens WHERE id = %s", (screen_id,))

    async def looking(self, person_id: int, within_s: float) -> bool:
        found = await self._run("SELECT EXISTS (SELECT 1 FROM live_screens WHERE person_id = %s "
                                "AND seen_at > now() - make_interval(secs => %s))", (person_id, within_s))
        return bool(found[0][0])

    async def showing(self, device_id: int, within_s: float) -> bool:
        found = await self._run("SELECT EXISTS (SELECT 1 FROM live_screens WHERE device_id = %s "
                                "AND seen_at > now() - make_interval(secs => %s))", (device_id, within_s))
        return bool(found[0][0])

    async def _prune(self, household_id: int) -> None:
        await self._run("DELETE FROM live_screens WHERE household_id = %s AND seen_at < now() - make_interval(secs => %s)",
                        (household_id, LEFT_BEHIND_S))

    async def _insert(self, owner: Literal["person_id", "device_id"], household_id: int, owner_id: int,
                      token: str | None) -> int:
        query: LiteralString = (
            "INSERT INTO live_screens (household_id, person_id, token) VALUES (%s, %s, %s::uuid) RETURNING id"
            if owner == "person_id" else
            "INSERT INTO live_screens (household_id, device_id, token) VALUES (%s, %s, %s::uuid) RETURNING id")
        made = await self._run(query, (household_id, owner_id, token))
        return int(made[0][0])

    async def _run(self, query: LiteralString, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall() if cur.description is not None else []
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ScreensUnavailable("database unavailable") from e
