"""Open screens in Postgres, table `live_screens`."""

from typing import Any, LiteralString

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .screens import Screens, ScreensUnavailable

LEFT_BEHIND_S = 86400
"""How long a row survives with no heartbeat before the next opening by that person removes it."""


class PostgresScreens(Screens):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def opened(self, household_id: int, person_id: int) -> int:
        await self._run("DELETE FROM live_screens WHERE person_id = %s AND seen_at < now() - make_interval(secs => %s)",
                        (person_id, LEFT_BEHIND_S))
        made = await self._run("INSERT INTO live_screens (household_id, person_id) VALUES (%s, %s) RETURNING id",
                           (household_id, person_id))
        return int(made[0][0])

    async def beat(self, screen_id: int) -> None:
        await self._run("UPDATE live_screens SET seen_at = now() WHERE id = %s", (screen_id,))

    async def closed(self, screen_id: int) -> None:
        await self._run("DELETE FROM live_screens WHERE id = %s", (screen_id,))

    async def looking(self, person_id: int, within_s: float) -> bool:
        found = await self._run("SELECT EXISTS (SELECT 1 FROM live_screens WHERE person_id = %s "
                                "AND seen_at > now() - make_interval(secs => %s))", (person_id, within_s))
        return bool(found[0][0])

    async def _run(self, query: LiteralString, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall() if cur.description is not None else []
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ScreensUnavailable("database unavailable") from e
