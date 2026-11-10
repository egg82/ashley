"""A household's model choices read from Postgres, table `household_routes`, and a conversation's household from
`conversations`. Contract: `route_choices.RouteChoiceReads`."""

from collections.abc import Mapping

from ..db.database import Database
from .model import Task
from .route_choices import Choice, RouteChoiceReads


class PostgresRouteChoices(RouteChoiceReads):
    def __init__(self, database: Database) -> None:
        raise NotImplementedError

    async def all(self) -> Mapping[int, Mapping[Task, Choice]]:
        raise NotImplementedError

    async def of_household(self, household_id: int) -> Mapping[Task, Choice]:
        raise NotImplementedError

    async def household_of(self, conversation_id: int) -> int | None:
        raise NotImplementedError
