"""Which routes a call walks for the household it serves (`ashley.services`): a third layer over the shipped routes
(`routes.json`) and the operator's (`ROUTES_FILE`).

**Layering.** A text task's routes are the shipped entry, replaced whole by the operator's when `ROUTES_FILE` gives
one (`routes.deployment`), then, for a task the household chose a model for, that model's route first and the
deployment's list after it with that route left out. So a chosen model that is unwired, resting or failing falls
through to the deployment's own routes, and a refusal is still final. A task whose deployment entry is `{"like": ...}`
follows the task it names, chosen model included (`escalated` follows `brainstorm`).

**Which tasks.** Only a task whose deployment entry says `"household": true` (`routes.Routes.households`): an explicit
field in the routes data, never a name. The operator turns it off for a task by giving that task a plain list in
`ROUTES_FILE`. `action_judge` is never one (`routes.NEVER_HOUSEHOLD`), whatever the data says; it is shown, not chosen.

**Options.** A household chooses among the deployment's own routes, never a route it writes: for a task, the task's
routes in order, then those of the other household tasks whose provider and model are not already listed, each keeping
its timeout and params. Only an option whose provider is wired now may be chosen.

**Validation and fallback.** The layered routes are built exactly as the deployment's are: the household's entries
overlaid on the deployment's data and checked by `routes.parse` against the same providers, then narrowed as the
deployment's are. A stored choice that is no longer an option (the operator dropped that model) is not applied and is
logged `inference.choice_dropped`; one whose provider lost its key stays applied, its route skipped as unwired so the
deployment's routes answer, and is logged `inference.choice_unwired` once per refresh while it lasts.

**Staleness.** Each pod caches every household's layered routes and reads the choices again on the first call once
the last read is `REFRESH_S` old, so a choice made on any pod reaches every pod's calls on both sites within that bound.
The cache is only a cache: a read that fails keeps what was built, and before any read succeeds every call walks the
deployment's routes."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..services import Service
from .model import Route, Task
from .route_choices import Choice, RoutesUnavailable
from .routes import Routes

Refusal = Literal["not_household", "not_offered", "unwired"]
"""Why a choice cannot be made: the task is not one a household chooses for, the provider and model are not one of the
task's options, or the option's provider is not wired now."""


@dataclass(frozen=True)
class TaskChoices:
    """One task as a household's room shows it. `household`: whether the household may choose for it. `routes`: the
    deployment's routes for it, in order. `chosen`: the household's stored choice, None when it has none (also for a
    task it may not choose for). `options`: what it may choose now, wired providers only, in order; empty when
    `household` is false."""

    task: Task
    household: bool
    routes: tuple[Route, ...]
    chosen: Choice | None
    options: tuple[Route, ...]


class HouseholdRoutes(Service):
    @classmethod
    def null(cls) -> "HouseholdRoutes":
        return NullHouseholdRoutes()

    @abstractmethod
    async def for_call(self, conversation_id: int | None) -> Routes:
        """The routes a text call serving `conversation_id` walks: its household's layered routes, or the deployment's
        when the call serves no conversation, its household chose nothing, or nothing could be read. A household with
        no choices gets the deployment's routes exactly. Reads the choices again first when they are `REFRESH_S` old.
        Never raises; a read that fails is logged `inference.choices_unreadable`."""

    @abstractmethod
    async def choices(self, household_id: int) -> tuple[TaskChoices, ...]:
        """For `household_id`'s room: every task it may choose for, in `Task` order, then `action_judge`, shown so a
        person can see which model judges. Read from the store, not the cache, so a choice just written is shown.
        Raises RoutesUnavailable."""

    @abstractmethod
    def refusal(self, task: Task, choice: Choice | None) -> Refusal | None:
        """Why `choice` may not be stored for `task` now, or None when it may (`Refusal`). None is clearing the choice,
        refused only for a task that is not a household's. Checked against the options and the providers wired at this
        moment; the cache re-checks at each read, since either may change."""


class NullHouseholdRoutes(HouseholdRoutes):
    """What an unwired process sees: no household routes. `for_call` cannot know the deployment's routes, so the
    router is never given this; the room's reads raise RoutesUnavailable and every choice is refused."""

    async def for_call(self, conversation_id: int | None) -> Routes:
        raise RoutesUnavailable("HouseholdRoutes is not wired")

    async def choices(self, household_id: int) -> tuple[TaskChoices, ...]:
        raise RoutesUnavailable("HouseholdRoutes is not wired")

    def refusal(self, task: Task, choice: Choice | None) -> Refusal | None:
        return "not_household"
