"""Wire shapes of the signed-in person's own voiceprints (`ashley.api.memory`)."""

from datetime import datetime

from pydantic import BaseModel, Field


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


class EnrolmentRequest(BaseModel):
    """Arm a speaker to enrol the signed-in person. There is no person field: it is always the session's. `wakes` is
    how many of the device's next wakes to enrol from, `enrol_wakes` in the voice config when left out."""

    device_id: int = Field(ge=1)
    wakes: int | None = Field(default=None, ge=1)


class Enrolment(BaseModel):
    """The armed enrolment: the device, how many of its next wakes will be stored, and when it lapses."""

    device_id: int
    wakes: int
    until: datetime
