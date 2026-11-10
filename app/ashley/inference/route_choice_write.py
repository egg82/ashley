"""The RouteChoiceWriter service (`ashley.services`): a person sets or clears the model their household chose for a
task. Kept apart from `route_choices.RouteChoiceReads`, which the router reads, so nothing she does on her own can
choose a model: only the spend room's route and the wiring import this module (`tests/test_settings_boundary.py`).
Callers import only this module and `route_choices`; the Postgres implementation lives beside it.

The choice is checked by `household_routes.HouseholdRoutes.refusal` before it is written, not here."""

from abc import abstractmethod

from ..services import Service
from .model import Task
from .route_choices import Choice, RoutesUnavailable


class RouteChoiceWriter(Service):
    @classmethod
    def null(cls) -> "RouteChoiceWriter":
        return NullRouteChoiceWriter()

    @abstractmethod
    async def put(self, household_id: int, person_id: int, task: Task, choice: Choice | None) -> None:
        """Store `choice` as `household_id`'s model for `task`, replacing any; None clears it. `person_id` is who set
        it, recorded with it. Logs `inference.choice_set` (household, person, task, provider and model, or `cleared`).
        Raises RoutesUnavailable."""


class NullRouteChoiceWriter(RouteChoiceWriter):
    """What an unwired process sees: every write raises RoutesUnavailable."""

    async def put(self, household_id: int, person_id: int, task: Task, choice: Choice | None) -> None:
        raise RoutesUnavailable("RouteChoiceWriter is not wired")
