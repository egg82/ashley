"""The Presence service (`ashley.services`): who in a household is home now. The first implementation reads Home
Assistant's `person` entities (`home_assistant_presence.HomeAssistantPresence`).

Who is where is people's data: logs carry counts, never ids of who is home."""

from abc import abstractmethod

from ..services import Service


class Presence(Service):
    @classmethod
    def null(cls) -> "Presence":
        return NullPresence()

    @abstractmethod
    async def home(self, household_id: int) -> frozenset[int] | None:
        """The ids of the people in that household who are home now. None when it cannot be known (the source
        unreachable, or no one in the household is mapped to it), never an empty set standing in for "unknown": an
        empty set means everyone mapped is known to be away. A person with no mapping is never in the set. Logs
        `presence.read` with the count home and duration_ms, or `presence.unknown` with the reason."""


class NullPresence(Presence):
    """Knows nothing: what an unwired process sees. Presence is a signal, not a dependency, so it answers None (unknown)
    rather than raising; the reply goes on with the speaker unknown."""

    async def home(self, household_id: int) -> frozenset[int] | None:
        return None
