"""Her tools for a camera's live feed on the screens (`screen_show_camera`, `screen_clear_camera`), for one turn
(`channels.turn_tools`): a known speaker, or a turn on a screen device's own thread, with a screen in reach and a camera
source connected. The feed goes where `ashley.channels.kiosk.feed.show` says and is the Cameras port's, so a camera she may
not look through is refused. Logged `tools.call` with the tool, outcome and screen count, never a camera's id or name."""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from ..inference.model import ToolCall, ToolResult
from ..live.screens import ScreensUnavailable
from ..tools import bench_results, camera_feed, screen_feed_specs
from ..tools.camera_specs import camera_id
from ..tools.tools import Catalogue, Tools
from .devices import DevicesUnavailable
from .kiosk import feed

_REFUSED = {"no_such_camera": "camera is not a camera you may look through; cameras lists them",
            "no_live_feed": "that camera gives no live video",
            "not_connected": "the household has no camera connected, or has switched cameras off",
            "unavailable": "the camera's service cannot be reached right now"}


def _now() -> datetime:
    return datetime.now(UTC)


class ScreenFeedTools(Tools):
    def __init__(self, household_id: int, person_id: int | None, device_id: int | None,
                 clock: Callable[[], datetime] = _now) -> None:
        self._household, self._person, self._device = household_id, person_id, device_id
        self._clock = clock

    async def catalogue(self) -> Catalogue:
        """The two tools when a screen is in reach and a camera source is connected, else none; none while either cannot be
        read, which a call says again."""
        try:
            if not await feed.screens_in_reach(self._household, self._person, self._device):
                return Catalogue((), None)
            served = await camera_feed.served(self._household)
        except (DevicesUnavailable, camera_feed.FeedRefused):
            return Catalogue((), None)
        return Catalogue(screen_feed_specs.specs(), screen_feed_specs.INSTRUCTIONS) if served else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the screens, the camera or the model did: each is an error result."""
        started = time.monotonic()
        try:
            if call.name == screen_feed_specs.SHOW:
                return await self._show(call, started)
            if call.name == screen_feed_specs.CLEAR:
                return await self._clear(call, started)
        except (ScreensUnavailable, DevicesUnavailable):
            return bench_results.failed(call, started, "unavailable", "the screens cannot be reached right now")
        return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")

    async def _show(self, call: ToolCall, started: float) -> ToolResult:
        chosen = camera_id(dict(call.arguments))
        if chosen is None:
            return bench_results.failed(call, started, "bad_arguments", "camera is a camera id as cameras gives it")
        reach = await feed.screens_in_reach(self._household, self._person, self._device)
        if not reach:
            return bench_results.failed(call, started, "no_such_screen", "no screen is in reach")
        try:
            await camera_feed.titled(self._household, chosen)
            await camera_feed.config(self._household, chosen)
        except camera_feed.FeedRefused as e:
            return bench_results.failed(call, started, e.reason, _REFUSED[e.reason])
        count = await feed.show(self._household, chosen, reach, self._clock(),
                                self._person if self._device is None else None)
        if not count:
            return bench_results.failed(call, started, "no_one_looking", "no screen in reach is open and in the foreground, so "
                                        "nobody saw it: tell the person it did not show", screens=0)
        return bench_results.ok(call, started, {"screens": count}, outside=False, screens=count)

    async def _clear(self, call: ToolCall, started: float) -> ToolResult:
        count = await feed.clear(self._household)
        return bench_results.ok(call, started, {"screens": count}, outside=False, screens=count)
