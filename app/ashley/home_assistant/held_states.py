"""The HeldStates service (`ashley.services`): the states of named things in a household's Home Assistant, told by
subscription while a holder holds them, so a watch on a thing needs no automation installed in the house. Only the
watches singleton holds (`hold`), so only the pod holding its lease keeps sockets open; anywhere else `states` reads
each thing once. `ha_held.SocketStates` implements it."""

from abc import abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..services import Service
from .house import HouseUnavailable


@dataclass(frozen=True)
class EntityState:
    """One thing's state now and the name the house shows for it."""

    state: str
    name: str


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


class NullHeldStates(HeldStates):
    """No household reaches a house."""

    async def hold(self, changed: Callable[[], None]) -> None:
        return None

    async def states(self, household_id: int, entity_ids: Sequence[str]) -> Mapping[str, EntityState | None] | None:
        raise HouseUnavailable("held states are not wired")
