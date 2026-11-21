"""A household's cameras as she sees them, whichever service holds them: plain records whose fields are stated in camera
terms. An adapter (for Home Assistant, `ashley.home_assistant.cameras`) fills them from its service's own shapes; nothing
outside it knows those shapes."""

from collections.abc import Awaitable, Callable
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
    own read, tainted as any other, and never logged. `taken` is None when the source states no time; one is never made up. A picture of a recording carries
    that recording's `title`, as the source writes it."""

    data: bytes
    media_type: str
    taken: datetime | None
    title: str | None = None


@dataclass(frozen=True)
class Recording:
    """What a camera's own detector captured, listed by its source: `id` is the source's own, `camera_id` the camera that
    holds it and `title` the label exactly as the source writes it (it may carry the kind and the time). Information
    for her to read; nothing parses it or keys on its words."""

    id: str
    camera_id: str
    title: str


@dataclass(frozen=True)
class Detection:
    """What a camera's own detector reported: the camera (`camera_id`, as `Camera.id`), the detector's own class
    (`kind`, a field the source states, never read out of text) and when it saw it (`at`). A neutral record; a source
    that tells more (a score, a zone, the still it judged) adds fields here."""

    camera_id: str
    kind: str
    at: datetime


DetectionRecorder = Callable[[Detection], Awaitable[None]]


@dataclass(frozen=True)
class IceServer:
    """One server a browser may use to reach a camera: its `urls`, and the `username` and `credential` it asks for, if any.
    The credential is never logged."""

    urls: tuple[str, ...]
    username: str | None
    credential: str | None


@dataclass(frozen=True)
class LiveConfig:
    """What a browser needs to open a live feed of a camera: the `ice_servers` to reach it through, and the name of the
    data channel its offer must carry (None when none)."""

    ice_servers: tuple[IceServer, ...]
    data_channel: str | None


@dataclass(frozen=True)
class Candidate:
    """One ICE candidate, as a browser makes and takes it. It holds addresses, so it is never logged."""

    candidate: str
    sdp_mid: str | None
    sdp_m_line_index: int | None
    username_fragment: str | None = None


@dataclass(frozen=True)
class LiveSession:
    """The service has taken the offer: later candidates for it name `session_id`."""

    session_id: str


@dataclass(frozen=True)
class LiveAnswer:
    """The camera's answer to the offer, as SDP, which holds addresses and is never logged."""

    sdp: str


@dataclass(frozen=True)
class LiveCandidate:
    """A candidate the camera's side offers the browser."""

    candidate: Candidate


@dataclass(frozen=True)
class LiveRefused:
    """The service could not set the feed up; `code` is its own short reason."""

    code: str


LiveSignal = LiveSession | LiveAnswer | LiveCandidate | LiveRefused
"""What comes back while a feed is being set up, in the order the service sends it."""


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


class NoSuchRecording(Exception):
    """The camera holds no recording with that id."""


class NoStill(Exception):
    """The camera gives no still on demand now."""


class NoLiveFeed(Exception):
    """The camera gives no live feed in the way asked (the service has none for it, or not this way)."""
