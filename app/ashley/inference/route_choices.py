"""What a household chose to carry its chat-facing tasks, as stored: one model per task, named by provider and model.
The route it stands for (timeout, params, variant) is never stored; it is resolved from the deployment's routes each
time they are read (`ashley.inference.household_routes`), so the operator's tuning of a model reaches every household
that chose it."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from .model import Task


@dataclass(frozen=True)
class Choice:
    """The model a household chose for one task: a route's `provider` and `model` (`model.Route`)."""

    provider: str
    model: str


class RoutesUnavailable(Exception):
    """The household's choices could not be read or written. Transient."""


class RouteChoiceReads(ABC):
    """The read side of the stored choices; the write side is `route_choice_write.RouteChoiceWriter`, kept apart so
    nothing that reads a choice can write one."""

    @abstractmethod
    async def all(self) -> Mapping[int, Mapping[Task, Choice]]:
        """Every household's choices, by household id then task; a household with none is absent. Raises
        RoutesUnavailable."""

    @abstractmethod
    async def of_household(self, household_id: int) -> Mapping[Task, Choice]:
        """`household_id`'s choices by task, empty when it has none. Raises RoutesUnavailable."""

    @abstractmethod
    async def household_of(self, conversation_id: int) -> int | None:
        """The household the conversation belongs to, which never changes; None when no conversation has that id.
        Raises RoutesUnavailable."""
