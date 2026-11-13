"""The Kubernetes media worker: each job in a pod of its own in the sandbox namespace (`media_pod.manifest`), running
`media_runner.py`; its answer read from the pod's log (`PodLog`). The pod fetches the file by a short-lived link of the
app's own (`ashley.files.links`), so no bytes pass through the app pod. Logs carry the pod, the job and its counts and
durations (`media.frames`, `media.transcribed`, `media.youtube_captions`), never the link, the file's name or what was seen or said."""

import base64
import binascii
import json
import logging
import time
from collections.abc import Awaitable, Callable
from importlib import resources
from typing import Any

from .. import logs
from ..files import links
from .captions import Segment, parse_captions
from .loose import as_list, as_object
from .media import Media, MediaUnavailable, Sheet, Source, Transcribed
from .media_config import MediaConfig
from .media_pod import manifest
from .pod_log import PodFailed, PodLog

log = logging.getLogger("ashley.runs")
RUNNER = resources.files("ashley.runs").joinpath("media_runner.py").read_text()
MARK = "ashley-media "
FAILED = "ashley-media-failed "


class KubernetesMedia(Media):
    def __init__(self, pods: PodLog, runtime_class: str, image: str, app_url: str, link_key: bytes,
                 whisper: Callable[[], Awaitable[str]],
                 config: MediaConfig, wall: Callable[[], float] = time.time) -> None:
        """`app_url` is where a pod in the namespace reaches the app, no trailing slash; `link_key` signs the file's link;
        `whisper` gives the speech service's Wyoming address as the pod reaches it, read for each transcription, empty for
        none (captions only)."""
        self._pods = pods
        self._runtime_class = runtime_class
        self._image = image
        self._app_url = app_url
        self._link_key = link_key
        self._whisper = whisper
        self._config = config
        self._wall = wall

    def available(self) -> bool:
        return True

    async def frames(self, name: str, source: Source, at: tuple[float, ...]) -> Sheet:
        """Raises MediaUnavailable (also for more than `max_frames` moments or none). Logs `media.frames` with the
        household, frames asked and duration."""
        if not 1 <= len(at) <= self._config.max_frames:
            raise MediaUnavailable("bad_frames")
        started = time.monotonic()
        done = await self._job(name, source, {"task": "frames", "at": list(at)}, self._config.frames_deadline_s)
        sheet = _sheet(done)
        logs.info(log, "media.frames", household=source.household_id, frames=sheet.count, bytes=len(sheet.jpeg),
                  duration_ms=_ms(started))
        return sheet

    async def transcribe(self, name: str, source: Source, language: str | None) -> Transcribed:
        """Raises MediaUnavailable. Logs `media.transcribed` with the household, where it came from, segments and
        duration."""
        started = time.monotonic()
        task: dict[str, Any] = {"task": "transcribe", "window_s": self._config.window_s,
                                "max_audio_s": self._config.max_audio_s, "whisper": await self._whisper(),
                                "model": self._config.whisper_model, "language": language}
        done = await self._job(name, source, task, self._config.transcribe_deadline_s)
        said = _transcribed(done)
        logs.info(log, "media.transcribed", household=source.household_id, source=said.source,
                  segments=len(said.segments), seconds=int(said.duration_s), duration_ms=_ms(started))
        return said

    async def youtube_captions(self, name: str, video_id: str) -> Transcribed:
        """Raises MediaUnavailable. Logs `media.youtube_captions` with the video id, segments and duration, or
        `media.youtube_captions_failed` with the reason. The pod carries the fetch label and gets no file link."""
        started = time.monotonic()
        task = {"task": "youtube_captions", "video_id": video_id}
        deadline = self._config.captions_deadline_s
        pod = manifest(name, "", task, deadline, self._config, self._image, self._runtime_class, RUNNER, fetch=True)
        try:
            said = _youtube(await self._answer(pod, deadline))
        except MediaUnavailable as e:
            logs.warning(log, "media.youtube_captions_failed", video=video_id, reason=e.reason, duration_ms=_ms(started))
            raise
        logs.info(log, "media.youtube_captions", video=video_id, segments=len(said.segments), seconds=int(said.duration_s),
                  duration_ms=_ms(started))
        return said

    async def _answer(self, pod: dict[str, Any], deadline_s: int) -> dict[str, Any]:
        try:
            return answer(await self._pods.run(pod, deadline_s))
        except PodFailed as e:
            raise MediaUnavailable(str(e)) from e

    async def _job(self, name: str, source: Source, task: dict[str, Any], deadline_s: int) -> dict[str, Any]:
        grant = links.Grant(source.household_id, source.sha256, source.media_type, False,
                            int(self._wall()) + self._config.link_ttl_s)
        url = self._app_url + links.mint(self._link_key, grant).url
        task = {**task, "size": source.size, "sha256": source.sha256}
        pod = manifest(name, url, task, deadline_s, self._config, self._image, self._runtime_class, RUNNER)
        return await self._answer(pod, deadline_s)


def answer(log_text: str) -> dict[str, Any]:
    """The JSON after the last `MARK` line of a media pod's log. Raises MediaUnavailable with the reason the runner gave
    (a `FAILED` line), or `no_answer` when the log holds neither."""
    for line in reversed(log_text.splitlines()):
        if line.startswith(MARK):
            try:
                found = as_object(json.loads(line[len(MARK):]))
            except ValueError as e:
                raise MediaUnavailable("bad_answer") from e
            if found is None:
                raise MediaUnavailable("bad_answer")
            return found
        if line.startswith(FAILED):
            raise MediaUnavailable(line[len(FAILED):].strip()[:40] or "failed")
    raise MediaUnavailable("no_answer")


def _sheet(done: dict[str, Any]) -> Sheet:
    try:
        jpeg = base64.b64decode(str(done["jpeg"]), validate=True)
        count, duration = int(done["count"]), float(done["duration"])
    except (KeyError, ValueError, TypeError, binascii.Error) as e:
        raise MediaUnavailable("bad_answer") from e
    if done.get("kind") != "frames" or not jpeg.startswith(b"\xff\xd8\xff"):
        raise MediaUnavailable("bad_answer")
    return Sheet(jpeg, count, duration)


def _transcribed(done: dict[str, Any]) -> Transcribed:
    try:
        duration = float(done["duration"])
        if done.get("kind") == "captions":
            return Transcribed("captions", duration, tuple(parse_captions(str(done["srt"]))))
        if done.get("kind") == "speech":
            return Transcribed("speech", duration, tuple(_segment(s) for s in as_list(done["segments"]) or []))
    except (KeyError, ValueError, TypeError) as e:
        raise MediaUnavailable("bad_answer") from e
    raise MediaUnavailable("bad_answer")


def _youtube(done: dict[str, Any]) -> Transcribed:
    try:
        duration = float(done["duration"])
        if done.get("kind") == "youtube":
            return Transcribed("youtube", duration, tuple(_segment(s) for s in as_list(done["segments"]) or []))
    except (KeyError, ValueError, TypeError) as e:
        raise MediaUnavailable("bad_answer") from e
    raise MediaUnavailable("bad_answer")


def _segment(raw: object) -> Segment:
    pair = as_list(raw)
    if pair is None or len(pair) != 2 or not isinstance(pair[1], str) or not isinstance(pair[0], (int, float)):
        raise ValueError("a segment is [start, text]")
    return Segment(float(pair[0]), pair[1])


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
