"""A household's model choices written in Postgres, table `household_routes`: one upsert or delete per write.
Contract: `route_choice_write`."""

import logging

from .. import logs
from ..db.database import Database
from .model import Task
from .postgres_route_choices import translated
from .route_choice_write import RouteChoiceWriter
from .route_choices import Choice

log = logging.getLogger("ashley.inference")
_PUT = (
    "INSERT INTO household_routes (household_id, task, provider, model, person_id) VALUES (%s, %s, %s, %s, %s) "
    "ON CONFLICT (household_id, task) DO UPDATE SET provider = excluded.provider, model = excluded.model, "
    "person_id = excluded.person_id, set_at = now()")


class PostgresRouteChoiceWriter(RouteChoiceWriter):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def put(self, household_id: int, person_id: int, task: Task, choice: Choice | None) -> None:
        with translated():
            async with self._database.connection() as conn:
                if choice is None:
                    await conn.execute("DELETE FROM household_routes WHERE household_id = %s AND task = %s",
                                       (household_id, task))
                else:
                    await conn.execute(_PUT, (household_id, task, choice.provider, choice.model, person_id))
        chosen = {"outcome": "cleared"} if choice is None else {"outcome": "set", "provider": choice.provider,
                                                                "model": choice.model}
        logs.info(log, "inference.choice_set", household=household_id, person=person_id, task=task, **chosen)
