"""A household's model choices written in Postgres, table `household_routes`. Contract: `route_choice_write`."""

from ..db.database import Database
from .model import Task
from .route_choice_write import RouteChoiceWriter
from .route_choices import Choice


class PostgresRouteChoiceWriter(RouteChoiceWriter):
    def __init__(self, database: Database) -> None:
        raise NotImplementedError

    async def put(self, household_id: int, person_id: int, task: Task, choice: Choice | None) -> None:
        raise NotImplementedError
