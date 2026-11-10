"""The Media service (`ashley.services`), the Strategy a recording is looked into through: a pod with ffmpeg that
fetches one file of the object store and either brings back a picture of the moments asked (`frames`) or what is said
in it (`transcribe`); a third job fetches no file and brings back a YouTube video's English captions
(`youtube_captions`), the one job whose pod reaches the internet. `media_kubernetes.KubernetesMedia` runs each in a pod
of the sandbox namespace beside code runs; the Null Object does none, so her tools for them are not offered. Callers import this module and ask the locator."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..services import Service
from .captions import Segment


class MediaUnavailable(Exception):
    """The job could not be done, for `reason` (a short word the pod or the runner gave: `no_video`, `no_audio`,
    `too_long`, `no_speech_service`, `speech_down`, `no_captions` (a YouTube video with no English track), `unreadable`, `timed_out`, ...). Nothing was kept."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Source:
    """The file to work on: object `household_id`/`sha256`, `size` bytes, judged to be `media_type`."""

    household_id: int
    sha256: str
    size: int
    media_type: str


@dataclass(frozen=True)
class Sheet:
    """What a frames job brings back: a JPEG of `count` frames laid out left to right and then down, in the order asked,
    of a recording `duration_s` long."""

    jpeg: bytes
    count: int
    duration_s: float


@dataclass(frozen=True)
class Transcribed:
    """What was said: `segments` from the file's own `captions`, by `speech` heard in windows, or from the captions of a
    `youtube` video."""

    source: Literal["captions", "speech", "youtube"]
    duration_s: float
    segments: tuple[Segment, ...]


class Media(Service):
    @classmethod
    def null(cls) -> "Media":
        return NullMedia()

    @abstractmethod
    def available(self) -> bool:
        """Whether it can do anything at all."""

    @abstractmethod
    async def frames(self, name: str, source: Source, at: tuple[float, ...]) -> Sheet:
        """The video `source` at the moments `at` (seconds; one to `MediaConfig.max_frames`, clamped into the file).
        `name` is unique per job and safe as a Kubernetes name (`media-<...>`). Raises MediaUnavailable. Leaves nothing
        behind: whatever did the work is gone when this returns or raises."""

    @abstractmethod
    async def transcribe(self, name: str, source: Source, language: str | None) -> Transcribed:
        """What is said in `source`, timestamped: the captions inside the file when it has some, else its sound
        through the speech service (in `language` when given). Raises MediaUnavailable. Leaves nothing behind."""

    @abstractmethod
    async def youtube_captions(self, name: str, video_id: str) -> Transcribed:
        """The English captions of the YouTube video `video_id` (its 11-character id; the worker builds the watch address
        itself), the manual track when there is one, else the automatic one, as `youtube` segments. Raises MediaUnavailable
        (`no_captions` when the video has no English track). Leaves nothing behind."""


class NullMedia(Media):
    def available(self) -> bool:
        return False

    async def frames(self, name: str, source: Source, at: tuple[float, ...]) -> Sheet:
        raise MediaUnavailable("not_wired")

    async def transcribe(self, name: str, source: Source, language: str | None) -> Transcribed:
        raise MediaUnavailable("not_wired")

    async def youtube_captions(self, name: str, video_id: str) -> Transcribed:
        raise MediaUnavailable("not_wired")
