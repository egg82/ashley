"""Her eyes through the household's cameras, for one turn (`channels.turn_tools`): `cameras` lists those she may look
through, `camera_look` gives her one still as an image in the result and `camera_recordings` lists what a camera's own
detector captured (`camera_look` with a `recording` shows one), through the Cameras port
(`ashley.cameras.cameras`). The still is made fit like a bench look's (`ashley.looks.pictures`) and kept with the turn as a
look (`ashley.tools.bench_picture`, on no bench), so the page shows what she saw and a turn takes at most
`max_looks_per_turn` of them. Offered to a known speaker in any chat while an object store is wired and the household has a
camera source. Arguments and results are never logged, nor a camera's name or a byte; `tools.call` carries the tool,
outcome and row count or size."""

import asyncio
import time
from dataclasses import replace

from .. import services
from ..cameras.cameras import Cameras
from ..cameras.model import CamerasFailed, CamerasUnavailable, NoStill, NoSuchCamera, NoSuchRecording, NotConnected
from ..files.store import ObjectStore, StoreUnavailable
from ..inference.model import Image, ToolCall, ToolResult
from ..looks import config as looks_config
from ..looks import pictures
from ..looks.looks import LooksUnavailable
from ..looks.pictures import CannotPrepare
from . import bench_picture, bench_results
from .camera_specs import CAMERAS, INSTRUCTIONS, LOOK, RECORDINGS, camera_id, look_arguments, specs
from .tools import Catalogue, Tools, ToolsUnavailable

CONFIG = looks_config.load()
_UNAVAILABLE = "the household's connections cannot be read"
_NOT_CONNECTED = "the household has no camera connected, or has switched cameras off"
_NO_SUCH = "camera is not a camera you may look through; cameras lists them"


class CameraTools(Tools):
    def __init__(self, household_id: int, conversation_id: int, turn_id: int) -> None:
        self._household_id = household_id
        self._said = (conversation_id, turn_id)

    async def catalogue(self) -> Catalogue:
        """No tools when no object store is wired (a picture is kept before she is given it) or the household has no
        camera source. Raises ToolsUnavailable when its link cannot be read."""
        if not await services.get(ObjectStore).available():
            return Catalogue((), None)
        try:
            served = await services.get(Cameras).connected(self._household_id)
        except CamerasUnavailable as e:
            raise ToolsUnavailable("cameras unavailable") from e
        return Catalogue(specs(), INSTRUCTIONS) if served else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no source, no still or a source failing are each an error result."""
        started = time.monotonic()
        if call.name == CAMERAS:
            return await self._list(call, started)
        if call.name == LOOK:
            return await self._look(call, started)
        if call.name == RECORDINGS:
            return await self._recordings(call, started)
        return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")

    async def _list(self, call: ToolCall, started: float) -> ToolResult:
        try:
            found = await services.get(Cameras).roster(self._household_id)
        except CamerasUnavailable:
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        body: dict[str, object] = {"cameras": [{"id": c.id, "title": c.title, "source": c.source} for c in found.cameras]}
        if found.unread:
            body["unread"] = list(found.unread)
        return bench_results.ok(call, started, body, rows=len(found.cameras))

    async def _recordings(self, call: ToolCall, started: float) -> ToolResult:
        chosen = camera_id(dict(call.arguments))
        if chosen is None:
            return bench_results.failed(call, started, "bad_arguments", "camera is a camera id as cameras gives it")
        try:
            found = await services.get(Cameras).recordings(self._household_id, chosen)
        except CamerasUnavailable:
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        except NoSuchCamera:
            return bench_results.failed(call, started, "bad_arguments", _NO_SUCH)
        except CamerasFailed as e:
            return bench_results.failed(call, started, e.reason, "the camera's service did not list its recordings")
        body: dict[str, object] = {"recordings": [{"id": r.id, "title": r.title} for r in found]}
        return bench_results.ok(call, started, body, rows=len(found))

    async def _look(self, call: ToolCall, started: float) -> ToolResult:
        asked = look_arguments(dict(call.arguments))
        if asked is None:
            return bench_results.failed(call, started, "bad_arguments", "camera is a camera id as cameras gives it, "
                                        "recording an id as camera_recordings gives it")
        chosen, recording = asked
        try:
            over = await bench_picture.over_limit(self._household_id, self._said[1], call.id, CONFIG.max_looks_per_turn)
            if over is not None:
                return bench_results.failed(call, started, "limit", over)
            cameras = services.get(Cameras)
            still = (await cameras.look(self._household_id, chosen) if recording is None
                     else await cameras.look_recording(self._household_id, chosen, recording))
            try:
                made = await asyncio.to_thread(pictures.prepare, still.data, None, CONFIG)
            except CannotPrepare as e:
                return bench_results.failed(call, started, e.outcome, e.reason)
            picture = Image("image/jpeg", made.data)
            await bench_picture.keep(self._household_id, self._said, call.id, None, None, picture)
        except CamerasUnavailable:
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        except NoSuchCamera:
            return bench_results.failed(call, started, "bad_arguments", _NO_SUCH)
        except NoSuchRecording:
            return bench_results.failed(call, started, "bad_arguments", "recording is not one of that camera's; "
                                        "camera_recordings lists them")
        except NoStill:
            return bench_results.failed(call, started, "no_still", "that camera gives no picture when asked; say so, "
                                        "and do not guess what it shows")
        except CamerasFailed as e:
            return bench_results.failed(call, started, e.reason, "the camera's service did not give a picture")
        except (StoreUnavailable, LooksUnavailable):
            return bench_results.failed(call, started, "unavailable", "the storage cannot be reached right now; "
                                        "nothing was looked at")
        body: dict[str, object] = {"picture": "follows in this result"}
        if still.taken is not None:
            body["taken"] = still.taken.isoformat(timespec="seconds")
        if still.title is not None:
            body["recording"] = still.title
        done = bench_results.ok(call, started, body, bytes=len(picture.data), px=made.px)
        return replace(done, images=(picture,))
