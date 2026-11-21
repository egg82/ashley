"""The Detections record (`ashley.services`): each detector event a camera reported, kept once so the event heard by a
pod on each site, or heard again, acts once, and so a camera's minimum gap between feeds counts from the last one shown.
Callers import only this module; `detections_postgres.PostgresDetections` implements it. A camera's id is stored, never
logged."""

from abc import abstractmethod
from datetime import datetime
from typing import Literal

from ..services import Service
from .model import Detection

Claim = Literal["new", "duplicate", "too_soon"]
"""`new`: first to record this detection and no feed was shown for the camera within the gap; `duplicate`: already
recorded; `too_soon`: recorded, but a feed was shown for the camera within the gap."""


class DetectionsUnavailable(Exception):
    """The record could not be read or written."""


class Detections(Service):
    @classmethod
    def null(cls) -> "Detections":
        return NullDetections()

    @abstractmethod
    async def claim(self, household_id: int, detection: Detection, min_gap_s: float) -> Claim:
        """Record `detection` for the household and say whether it may act. Atomic per camera, across pods. Raises
        DetectionsUnavailable."""

    @abstractmethod
    async def shown(self, household_id: int, detection: Detection) -> None:
        """A feed was put on the screens for the detection `claim` said was new; the gap counts from it. Raises
        DetectionsUnavailable."""

    @abstractmethod
    async def prune(self, now: datetime, keep_s: float) -> int:
        """Drop the detections older than `keep_s` before `now`; how many. Raises DetectionsUnavailable."""


class NullDetections(Detections):
    """Records nothing, so nothing acts: what an unwired process sees."""

    async def claim(self, household_id: int, detection: Detection, min_gap_s: float) -> Claim:
        raise DetectionsUnavailable("Detections is not wired")

    async def shown(self, household_id: int, detection: Detection) -> None:
        raise DetectionsUnavailable("Detections is not wired")

    async def prune(self, now: datetime, keep_s: float) -> int:
        raise DetectionsUnavailable("Detections is not wired")
