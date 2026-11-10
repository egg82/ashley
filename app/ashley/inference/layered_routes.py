"""The HouseholdRoutes implementation: a per-pod cache of every household's layered routes over `RouteChoiceReads`.
Contract: `household_routes`."""

import time
from collections.abc import Callable, Collection, Mapping

from .household_routes import HouseholdRoutes, Refusal, TaskChoices
from .model import Task
from .provider import Wired
from .route_choices import Choice, RouteChoiceReads
from .routes import Routes

REFRESH_S = 30.0
"""How old the choices read last may be before a call reads them again: the bound on how long a pod walks routes a
household has since changed on another pod."""


class LayeredRoutes(HouseholdRoutes):
    """`deployment` is the deployment's routes data (`routes.deployment`); `checkers` the providers its routes are
    checked against (`routes.parse`'s `providers`: every provider a key could turn on); `wired` the names of the
    providers wired now, asked at each check; `reads` the stored choices; `narrow` what the deployment's routes were
    narrowed by before the router got them (`routes.without_fallback` in the app), applied to each household's too.
    `clock` is monotonic seconds. Raises ValueError when `deployment` does not parse."""

    def __init__(self, deployment: Mapping[str, object], checkers: Mapping[str, Wired],
                 wired: Callable[[], Collection[str]], reads: RouteChoiceReads,
                 narrow: Callable[[Routes], Routes] = lambda r: r, clock: Callable[[], float] = time.monotonic,
                 refresh_s: float = REFRESH_S) -> None:
        raise NotImplementedError

    def deployment(self) -> Routes:
        """The deployment's routes, narrowed: what a call walks for a household with no choices."""
        raise NotImplementedError

    async def for_call(self, conversation_id: int | None) -> Routes:
        raise NotImplementedError

    async def choices(self, household_id: int) -> tuple[TaskChoices, ...]:
        raise NotImplementedError

    def refusal(self, task: Task, choice: Choice | None) -> Refusal | None:
        raise NotImplementedError
