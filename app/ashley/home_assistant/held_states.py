"""The HeldStates service (`ashley.services`): the states of named things in a household's Home Assistant, told by
subscription while a holder holds them, so a watch on a thing needs no automation installed in the house. Only the
watches singleton holds (`hold`), so only the pod holding its lease keeps sockets open; anywhere else `states` reads
each thing once. `ha_held.SocketStates` implements it."""

from abc import abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from ..services import Service
from .house import HouseUnavailable


@dataclass(frozen=True)
class EntityState:
    """One thing's state now and the name the house shows for it."""

    state: str
    name: str


@dataclass(frozen=True)
class HouseEvent:
    """One event Home Assistant fired: its `type`, its `data` object, when it fired (`at`) and its context's id, which
    tells a retold event from a second one."""

    type: str
    data: Mapping[str, object]
    at: datetime
    context: str


Recorder = Callable[[HouseEvent], Awaitable[None]]


class HeldStates(Service):
    @classmethod
    def null(cls) -> "HeldStates":
        return NullHeldStates()

    @abstractmethod
    async def hold(self, changed: Callable[[], None]) -> None:
        """Hold a socket per household that `states` was asked about, until cancelled, calling `changed` whenever a
        subscribed thing changes state or a socket comes back after a drop (so a change during the gap is read). Never
        raises but CancelledError."""

    @abstractmethod
    async def states(self, household_id: int, entity_ids: Sequence[str]) -> Mapping[str, EntityState | None] | None:
        """Each of `entity_ids` now, None for one the house does not have; None for a household with no Home Assistant.
        While held, the things are subscribed (the first ask reads them over the held socket, later ones answer from
        what it was told) and a thing not asked about for `idle_s` is let go. Raises HouseUnavailable when the house
        cannot be reached, HomesUnavailable when which house is the household's cannot be read."""

    @abstractmethod
    async def events(self, household_id: int, types: Mapping[str, Recorder]) -> None:
        """While held, hand each Home Assistant event of the household of one of `types` to its recorder as it
        arrives, and let go of any type held before and not named (none named lets go of all); a socket that dropped
        subscribes them again, an event while it was down is not told. A recorder that raises loses that one event,
        logged. Raises HouseUnavailable when the house cannot be reached or nothing holds, HomesUnavailable when which
        house is the household's cannot be read; a household with no Home Assistant holds nothing."""


class NullHeldStates(HeldStates):
    """No household reaches a house."""

    async def hold(self, changed: Callable[[], None]) -> None:
        return None

    async def states(self, household_id: int, entity_ids: Sequence[str]) -> Mapping[str, EntityState | None] | None:
        raise HouseUnavailable("held states are not wired")

    async def events(self, household_id: int, types: Mapping[str, Recorder]) -> None:
        raise HouseUnavailable("held states are not wired")
