"""Wire shapes of the signed-in person's own voiceprints (`ashley.api.memory`)."""

from datetime import datetime

from pydantic import BaseModel


class Voiceprint(BaseModel):
    """One print of the reader's voice: the name of the device it was enrolled on and when. The vector is never sent."""

    device: str
    enrolled_at: datetime


class VoiceprintsResponse(BaseModel):
    """The reader's own prints, oldest first; empty when none are enrolled. Nobody else's."""

    prints: list[Voiceprint]


class VoiceForgotten(BaseModel):
    """How many of the reader's prints were deleted, and any enrolment armed for them was cancelled; 0 when there were
    none."""

    deleted: int
