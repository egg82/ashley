"""Her eyes through the household's cameras, for one turn (`channels.turn_tools`): `cameras` lists those she may look
through and `camera_look` gives her one still as an image in the result, through the Cameras port
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
from ..cameras.model import CamerasFailed, CamerasUnavailable, NoStill, NoSuchCamera, NotConnected
from ..files.store import ObjectStore, StoreUnavailable
from ..inference.model import Image, ToolCall, ToolResult
from ..looks import config as looks_config
from ..looks import pictures
from ..looks.looks import LooksUnavailable
from ..looks.pictures import CannotPrepare
from . import bench_picture, bench_results
from .camera_specs import CAMERAS, INSTRUCTIONS, LOOK, camera_id, specs
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

    async def _look(self, call: ToolCall, started: float) -> ToolResult:
        chosen = camera_id(dict(call.arguments))
        if chosen is None:
            return bench_results.failed(call, started, "bad_arguments", "camera is a camera id as cameras gives it")
        try:
            over = await bench_picture.over_limit(self._household_id, self._said[1], call.id, CONFIG.max_looks_per_turn)
            if over is not None:
                return bench_results.failed(call, started, "limit", over)
            still = await services.get(Cameras).look(self._household_id, chosen)
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
        except NoStill:
            return bench_results.failed(call, started, "no_still", "that camera gives no picture when asked; say so, "
                                        "and do not guess what it shows")
        except CamerasFailed as e:
            return bench_results.failed(call, started, e.reason, "the camera's service did not give a picture")
        except (StoreUnavailable, LooksUnavailable):
            return bench_results.failed(call, started, "unavailable", "the storage cannot be reached right now; "
                                        "nothing was looked at")
        body: dict[str, object] = {"taken": still.taken.isoformat(timespec="seconds"), "picture": "follows in this result"}
        done = bench_results.ok(call, started, body, bytes=len(picture.data), px=made.px)
        return replace(done, images=(picture,))
