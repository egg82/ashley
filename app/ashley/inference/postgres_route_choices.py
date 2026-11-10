"""A household's model choices read from Postgres, table `household_routes`, and a conversation's household from
`conversations`. Contract: `route_choices.RouteChoiceReads`."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import LiteralString

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .model import Task
from .route_choices import Choice, RouteChoiceReads, RoutesUnavailable
from .routes import TASKS


@contextmanager
def translated() -> Generator[None]:
    """A database out of reach as RoutesUnavailable."""
    try:
        yield
    except DatabaseUnavailable as e:
        raise RoutesUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise RoutesUnavailable("database unreachable") from e


class PostgresRouteChoices(RouteChoiceReads):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def all(self) -> Mapping[int, Mapping[Task, Choice]]:
        out: dict[int, dict[Task, Choice]] = {}
        for household, task, choice in await self._rows("SELECT household_id, task, provider, model FROM household_routes",
                                                        ()):
            out.setdefault(household, {})[task] = choice
        return out

    async def of_household(self, household_id: int) -> Mapping[Task, Choice]:
        rows = await self._rows("SELECT household_id, task, provider, model FROM household_routes WHERE household_id = %s",
                                (household_id,))
        return {task: choice for _, task, choice in rows}

    async def household_of(self, conversation_id: int) -> int | None:
        with translated():
            async with self._database.connection() as conn:
                row = await (await conn.execute("SELECT household_id FROM conversations WHERE id = %s",
                                                (conversation_id,))).fetchone()
        return None if row is None else int(row[0])

    async def _rows(self, sql: LiteralString, args: tuple[int, ...]) -> list[tuple[int, Task, Choice]]:
        """Each stored choice as (household, task, choice); a task the code no longer knows is left out."""
        with translated():
            async with self._database.connection() as conn:
                rows = await (await conn.execute(sql, args)).fetchall()
        return [(int(h), t, Choice(str(p), str(m))) for h, t, p, m in rows if t in TASKS]
