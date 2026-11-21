"""A household's cameras as she sees them, whichever service holds them: plain records whose fields are stated in camera
terms. An adapter (for Home Assistant, `ashley.home_assistant.cameras`) fills them from its service's own shapes; nothing
outside it knows those shapes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Reason = Literal["refused", "unreachable", "unrecognised"]
"""Why a read failed: `refused`, the service turned the household's credentials or the request away; `unreachable`, no
answer in time or a server error; `unrecognised`, the answer is not the service's own shape."""


@dataclass(frozen=True)
class Camera:
    """One camera she may look through: `id` is the service's own, `title` what it is called there, `source` the kind of
    connection that holds it and `connection_id` which one."""

    id: str
    title: str
    source: str
    connection_id: int


@dataclass(frozen=True)
class Still:
    """One picture from a camera: its `data`, the `media_type` the service gave it and when it was `taken`. The household's
    own read, tainted as any other, and never logged."""

    data: bytes
    media_type: str
    taken: datetime


@dataclass(frozen=True)
class Roster:
    """The cameras she may look through and the `unread` sources (connection kinds) that could not be read now, whose
    cameras are missing."""

    cameras: tuple[Camera, ...]
    unread: tuple[str, ...]


class CamerasFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class CamerasUnavailable(Exception):
    """The household's connections cannot be read now."""


class NotConnected(Exception):
    """The household has no camera source switched on."""


class NoSuchCamera(Exception):
    """No camera she may look through, of the household's serving connections, has that id."""


class NoStill(Exception):
    """The camera gives no still on demand now."""
