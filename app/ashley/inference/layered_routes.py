"""The HouseholdRoutes implementation: a per-pod cache of every household's layered routes over `RouteChoiceReads`.
Contract: `household_routes`."""

import asyncio
import logging
import time
from collections.abc import Callable, Collection, Mapping

from .. import logs
from . import route_layers
from .household_routes import HouseholdRoutes, Refusal, TaskChoices
from .model import Route, Task
from .provider import Wired
from .route_choices import Choice, RouteChoiceReads, RoutesUnavailable
from .routes import NEVER_HOUSEHOLD, TASKS, Routes, parse

log = logging.getLogger("ashley.inference")

REFRESH_S = 30.0
"""How old the choices read last may be before a call reads them again: the bound on how long a pod walks routes a
household has since changed on another pod."""

_HOMES_MAX = 4096
"""How many conversations' households a pod remembers before it starts again; a conversation's household never
changes, so forgetting costs one read."""


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
        self._data = deployment
        self._checkers = checkers
        self._parsed = parse(deployment, checkers)
        self._deployment = narrow(self._parsed)
        self._options = route_layers.options(self._parsed)
        self._wired = wired
        self._reads = reads
        self._narrow = narrow
        self._clock = clock
        self._refresh_s = refresh_s
        self._lock = asyncio.Lock()
        self._read_at: float | None = None
        self._layered: dict[int, Routes] = {}
        self._homes: dict[int, int] = {}

    def deployment(self) -> Routes:
        """The deployment's routes, narrowed: what a call walks for a household with no choices."""
        return self._deployment

    async def for_call(self, conversation_id: int | None) -> Routes:
        await self._refresh()
        if conversation_id is None or not self._layered:
            return self._deployment
        household = await self._household_of(conversation_id)
        return self._deployment if household is None else self._layered.get(household, self._deployment)

    async def choices(self, household_id: int) -> tuple[TaskChoices, ...]:
        chosen = await self._reads.of_household(household_id)
        wired = set(self._wired())
        shown = [TaskChoices(t, True, self._deployment.by_task[t], chosen.get(t),
                             tuple(o for o in self._options[t] if o.provider in wired))
                 for t in TASKS if t in self._parsed.households]
        return (*shown, *(TaskChoices(t, False, self._deployment.by_task[t], None, ())
                          for t in TASKS if t in NEVER_HOUSEHOLD))

    def refusal(self, task: Task, choice: Choice | None) -> Refusal | None:
        if task not in self._parsed.households:
            return "not_household"
        if choice is None:
            return None
        option = route_layers.offered(self._options, task, choice)
        if option is None:
            return "not_offered"
        return None if option.provider in self._wired() else "unwired"

    async def _household_of(self, conversation_id: int) -> int | None:
        known = self._homes.get(conversation_id)
        if known is not None:
            return known
        try:
            found = await self._reads.household_of(conversation_id)
        except RoutesUnavailable:
            logs.warning(log, "inference.choices_unreadable", conversation=conversation_id)
            return None
        except Exception:
            logs.error(log, "inference.choices_unreadable", exc=True, conversation=conversation_id)
            return None
        if found is not None:
            if len(self._homes) >= _HOMES_MAX:
                self._homes.clear()
            self._homes[conversation_id] = found
        return found

    async def _refresh(self) -> None:
        if not self._due():
            return
        async with self._lock:
            if not self._due():
                return
            self._read_at = self._clock()
            try:
                stored = await self._reads.all()
            except RoutesUnavailable:
                logs.warning(log, "inference.choices_unreadable")
                return
            except Exception:
                logs.error(log, "inference.choices_unreadable", exc=True)
                return
            self._layered = {h: r for h, chosen in stored.items() if (r := self._layer(h, chosen)) is not None}

    def _due(self) -> bool:
        return self._read_at is None or self._clock() - self._read_at >= self._refresh_s

    def _layer(self, household: int, chosen: Mapping[Task, Choice]) -> Routes | None:
        """The household's routes with each choice still offered laid over the deployment's; None when none is."""
        routes = self._applied(household, chosen)
        if not routes:
            return None
        try:
            return self._narrow(route_layers.layered(self._data, self._checkers, self._parsed, routes))
        except ValueError:
            logs.warning(log, "inference.choice_dropped", household=household, tasks=len(routes), reason="invalid")
            return None

    def _applied(self, household: int, chosen: Mapping[Task, Choice]) -> dict[Task, Route]:
        """Each choice's route, logging the ones not applied (`choice_dropped`) and those whose provider is unwired
        now (`choice_unwired`), which still apply."""
        wired = set(self._wired())
        routes: dict[Task, Route] = {}
        for task, choice in chosen.items():
            option = route_layers.offered(self._options, task, choice)
            if option is None:
                logs.warning(log, "inference.choice_dropped", household=household, task=task,
                             provider=choice.provider, model=choice.model, reason="not_offered")
                continue
            if option.provider not in wired:
                logs.warning(log, "inference.choice_unwired", household=household, task=task,
                             provider=option.provider, model=option.model)
            routes[task] = option
        return routes
