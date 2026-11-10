"""The Voices service (`ashley.services`): the voiceprints enrolled for a household's people, and which devices are
enrolling someone now (`decisions.md`, "A voice names the speaker as a hint"). Prints are vectors, never audio.
Vectors and who was enrolled are never logged; device ids and counts are."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ...inference.voiceprint import Voiceprint
from ...services import Service


class VoicesUnavailable(Exception):
    """The database could not be reached. Transient."""


class UnknownEnrolee(Exception):
    """The device or person is not known, or they are not in one household."""


@dataclass(frozen=True)
class Enrolled:
    """A print stored by an armed device: for `person_id`, with `remaining` wakes left armed (0: enrolment is over)."""

    person_id: int
    remaining: int


@dataclass(frozen=True)
class PersonPrints:
    """One person's prints made by one model, oldest first; never empty."""

    person_id: int
    vectors: tuple[tuple[float, ...], ...]


class Voices(Service):
    @classmethod
    def null(cls) -> "Voices":
        return NullVoices()

    @abstractmethod
    async def prints(self, household_id: int, model: str) -> tuple[PersonPrints, ...]:
        """Every person in that household with at least one print made by `model`, ordered by person id; empty when
        none. Raises VoicesUnavailable."""

    @abstractmethod
    async def arm(self, device_id: int, person_id: int, wakes: int, until: datetime) -> None:
        """Arm `device_id` to enrol `person_id` for its next `wakes` wakes (positive), until `until`, replacing any
        enrolment the device was armed for. Raises ValueError for `wakes` under 1; UnknownEnrolee; VoicesUnavailable."""

    @abstractmethod
    async def enrol(self, device_id: int, voiceprint: Voiceprint) -> Enrolled | None:
        """When `device_id` is armed now (wakes left and `until` not passed, by the database's clock), store `voiceprint`
        for the armed person and count one wake off, in one transaction, so two wakes cannot both take the last one;
        None, storing nothing, when it is not. Raises VoicesUnavailable."""

    @abstractmethod
    async def forget(self, person_id: int) -> int:
        """Delete every print of `person_id`, and any enrolment armed for them; how many prints went. Raises
        VoicesUnavailable."""


class NullVoices(Voices):
    """Knows no voices and stores none: what an unwired process sees. Voice is a signal, not a dependency, so reads
    answer nothing and an enrolment is not armed; only the admin's writes raise."""

    async def prints(self, household_id: int, model: str) -> tuple[PersonPrints, ...]:
        return ()

    async def arm(self, device_id: int, person_id: int, wakes: int, until: datetime) -> None:
        raise VoicesUnavailable("Voices is not wired")

    async def enrol(self, device_id: int, voiceprint: Voiceprint) -> Enrolled | None:
        return None

    async def forget(self, person_id: int) -> int:
        raise VoicesUnavailable("Voices is not wired")
