"""The Clips service (`ashley.services`): her spoken reply, held briefly for a satellite, a room speaker or a screen to
fetch at `GET /api/voice/clips/{token}`; a clip announced on a screen also carries the line it shows
(`GET /api/voice/clips/{token}/line`). A clip is text, not audio: the speech is synthesised on the fetch, so any pod on either
site can serve it. The token is random, returned once, and stored only as its SHA-256; tokens and text are never
logged, clip and device ids are."""

from abc import abstractmethod
from dataclasses import dataclass

from ...services import Service


class ClipsUnavailable(Exception):
    """The database could not be reached. Transient."""


@dataclass(frozen=True)
class NewClip:
    """A stored clip: its id for logs, and the token for its URL, which exists nowhere else."""

    id: int
    token: str


@dataclass(frozen=True)
class Clip:
    """What a fetch needs: the text to speak, already respelled for the voice; the device whose wake it answers; and
    how long ago that wake was, by the database's clock, when the clip was read (`since_wake_ms`); and the line a
    screen shows beside it, None for a clip no screen shows."""

    id: int
    device_id: int
    body: str
    since_wake_ms: int
    line: str | None = None


class Clips(Service):
    @classmethod
    def null(cls) -> "Clips":
        return NullClips()

    @abstractmethod
    async def add(self, device_id: int, body: str, since_wake_ms: int, line: str | None = None) -> NewClip:
        """Store `body` (non-empty) for `device_id`, whose wake was `since_wake_ms` ago, with `line` (non-empty, or None)
        for a screen to show, committed before this returns, so the URL is fetchable the moment it is sent. The same
        write deletes every clip older than the retention. Raises ClipsUnavailable."""

    @abstractmethod
    async def get(self, token: str) -> Clip | None:
        """The clip `token` names, None when it names none or the clip is older than the retention. Raises
        ClipsUnavailable."""


class NullClips(Clips):
    """Stores nothing: every call raises ClipsUnavailable, so an unwired process fails the run rather than sending a
    URL that leads nowhere."""

    async def add(self, device_id: int, body: str, since_wake_ms: int, line: str | None = None) -> NewClip:
        raise ClipsUnavailable("Clips is not wired")

    async def get(self, token: str) -> Clip | None:
        raise ClipsUnavailable("Clips is not wired")
