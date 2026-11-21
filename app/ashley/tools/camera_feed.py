"""A camera's live feed as a screen's page asks for it, through the Cameras port (`ashley.cameras.cameras`): the cameras
she may put on a screen, what a browser needs to open one, the offer relayed to the camera's service with what comes back,
and the browser's candidates. The media never passes through her; she carries only the signalling, so the service's
token never reaches a page. Results are plain dicts the screens' routes send as they are (`ashley.api.screen_feed`).
Logs `camera.live` (the port) with the source, outcome and duration; nothing here logs an offer, an answer or a candidate."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Literal

from .. import services
from ..cameras.cameras import Cameras
from ..cameras.model import (Candidate, CamerasFailed, CamerasUnavailable, LiveAnswer, LiveCandidate, LiveSession, LiveSignal, NoLiveFeed, NoSuchCamera, NotConnected)

Refusal = Literal["no_such_camera", "no_live_feed", "not_connected", "unavailable"]


class FeedRefused(Exception):
    """The feed cannot be had: the camera is not one she may show (`no_such_camera`), gives no live feed
    (`no_live_feed`), the household has no camera source on (`not_connected`), or its service could not be reached
    (`unavailable`)."""

    def __init__(self, reason: Refusal) -> None:
        super().__init__(reason)
        self.reason: Refusal = reason


def _refusal(e: Exception) -> FeedRefused:
    if isinstance(e, NoSuchCamera):
        return FeedRefused("no_such_camera")
    if isinstance(e, NoLiveFeed):
        return FeedRefused("no_live_feed")
    if isinstance(e, NotConnected):
        return FeedRefused("not_connected")
    return FeedRefused("unavailable")


_FAILURES = (NoSuchCamera, NoLiveFeed, NotConnected, CamerasUnavailable, CamerasFailed)


async def served(household_id: int) -> bool:
    """Whether the household has a camera source on now. Raises FeedRefused (`unavailable`) when its connections cannot be
    read."""
    try:
        return await services.get(Cameras).connected(household_id)
    except CamerasUnavailable as e:
        raise FeedRefused("unavailable") from e


async def titled(household_id: int, camera_id: str) -> str:
    """The camera's title, for a card to show; the camera must be one she may show. A source that could not be read is
    `unavailable`, never "no such camera". Raises FeedRefused."""
    try:
        roster = await services.get(Cameras).roster(household_id)
    except (NotConnected, CamerasUnavailable) as e:
        raise _refusal(e) from e
    found = next((c.title for c in roster.cameras if c.id == camera_id), None)
    if found is None:
        raise FeedRefused("unavailable" if roster.unread else "no_such_camera")
    return found


async def config(household_id: int, camera_id: str) -> dict[str, object]:
    """What a browser needs to open the feed: `ice_servers` (each `urls`, `username`, `credential`) and `data_channel`
    (the channel its offer must carry, or null). Raises FeedRefused."""
    try:
        got = await services.get(Cameras).live_config(household_id, camera_id)
    except _FAILURES as e:
        raise _refusal(e) from e
    return {"ice_servers": [{"urls": list(s.urls), "username": s.username, "credential": s.credential}
                            for s in got.ice_servers], "data_channel": got.data_channel}


def relay(household_id: int, camera_id: str, offer: str) -> AbstractAsyncContextManager[AsyncIterator[dict[str, object]]]:
    """Pass the browser's `offer` (SDP) to the camera and yield what comes back as dicts: `session` (`session_id`),
    `answer` (`answer`), `candidate` (`candidate`: `candidate`, `sdp_mid`, `sdp_m_line_index`, `username_fragment`) and
    `error` (`code`), for as long as the context is open: the service ends the feed when it closes. Raises FeedRefused
    on entering."""
    return _relay(household_id, camera_id, offer)


@asynccontextmanager
async def _relay(household_id: int, camera_id: str, offer: str) -> AsyncGenerator[AsyncIterator[dict[str, object]]]:
    try:
        async with services.get(Cameras).live(household_id, camera_id, offer) as signals:
            yield _wire(signals)
    except _FAILURES as e:
        raise _refusal(e) from e


async def candidate(household_id: int, camera_id: str, session_id: str, line: str, sdp_mid: str | None,
                    sdp_m_line_index: int | None, username_fragment: str | None) -> None:
    """Hand the browser's candidate (as `relay` yields one) for the feed `session_id` on. Raises FeedRefused."""
    try:
        await services.get(Cameras).live_candidate(household_id, camera_id, session_id,
                                                   Candidate(line, sdp_mid, sdp_m_line_index, username_fragment))
    except _FAILURES as e:
        raise _refusal(e) from e


async def _wire(signals: AsyncIterator[LiveSignal]) -> AsyncIterator[dict[str, object]]:
    async for signal in signals:
        if isinstance(signal, LiveSession):
            yield {"type": "session", "session_id": signal.session_id}
        elif isinstance(signal, LiveAnswer):
            yield {"type": "answer", "answer": signal.sdp}
        elif isinstance(signal, LiveCandidate):
            c = signal.candidate
            yield {"type": "candidate", "candidate": c.candidate, "sdp_mid": c.sdp_mid,
                   "sdp_m_line_index": c.sdp_m_line_index, "username_fragment": c.username_fragment}
        else:
            yield {"type": "error", "code": signal.code}
