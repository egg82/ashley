"""`GET /api/live`: the open screens' feed for a signed-in person, as Server-Sent Events. Each `data:` line is one
`LiveEvent` in JSON, carrying only what this person may be shown (`ashley.live.events.shown_to`). A comment line comes
at least every `heartbeat_s`, which keeps the Cloudflare tunnel and proxies from closing an idle stream, and the
stream ends after `stream_s`, so the browser reconnects and its session is checked again. Nothing about the screen is
kept beyond the open connection: a screen that reconnects reads back what it shows, as on a `resync`.

A person's stream is also recorded as an open screen (`ashley.live.screens.Screens`), refreshed at the heartbeat, so a
turn nobody watches can tell they are away; the record failing never ends the stream (`live.screens_unavailable`).

Logs `live.opened` with the person id; `live.closed` (`fanout`) when it ends. `stream_to` is shared with the kiosk's own
feed (`kiosk_live`)."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import logs, services
from ..live import live as live_config
from ..live.events import BenchChanged, BenchCued, Event, HerState, PageMoved, ScreenChanged, TurnFailed, Viewer, Watcher
from ..live.fanout import Resync, Subscription
from ..live.live import Live, LiveUnavailable
from ..live.screens import Screens, ScreensUnavailable
from .live_models import LiveBench, LiveCue, LiveEvent, LiveFailed, LivePage, LiveResync, LiveScreen, LiveState, LiveTurn
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api.live")
CONFIG = live_config.load()
HEARTBEAT = b": \n\n"
_JSON_ERROR = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}


class EventStream(StreamingResponse):
    media_type = "text/event-stream"


@router.get("/api/live", response_class=EventStream, response_model=None, responses={
    200: {"model": LiveEvent, "description": "A stream of `LiveEvent`, one per `data:` line",
          "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/LiveEvent"}}}},
    401: {"description": "`unauthorized`: no live session", "content": _JSON_ERROR},
    503: {"description": "`unavailable`: no live feed; look for changes by asking again", "content": _JSON_ERROR}})
async def live(signed_in: Person) -> Response:
    """200 a stream of `LiveEvent`; 401 `unauthorized`; 503 `unavailable`."""
    who = signed_in.person
    return stream_to(Viewer(who.household_id, who.id), person=who.id)


def stream_to(viewer: Watcher, **opened: int) -> Response:
    """The stream of what `viewer` may be shown, or 503 `unavailable` when no feed is wired; `opened` (the person or
    device id) goes in the `live.opened` log."""
    try:
        subscription = services.get(Live).subscribe(viewer)
    except LiveUnavailable:
        body = ErrorResponse(code="unavailable", detail="no live feed; ask again for changes")
        return JSONResponse(status_code=503, content=body.model_dump())
    logs.info(log, "live.opened", **opened)
    return EventStream(_stream(subscription, viewer if isinstance(viewer, Viewer) else None), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _stream(subscription: Subscription, person: Viewer | None) -> AsyncIterator[bytes]:
    ends = time.monotonic() + CONFIG.stream_s
    screen = None if person is None else await _screen(lambda s: s.opened(person.household_id, person.person_id))
    beat_at = time.monotonic()
    try:
        async with subscription:
            yield HEARTBEAT
            while (left := ends - time.monotonic()) > 0:
                got = await subscription.next(min(CONFIG.heartbeat_s, left))
                if screen is not None and time.monotonic() - beat_at >= CONFIG.heartbeat_s:
                    beat_at = time.monotonic()
                    await _screen(lambda s: s.beat(screen))
                yield HEARTBEAT if got is None else frame(got)
    finally:
        if screen is not None:
            await _screen(lambda s: s.closed(screen))


async def _screen(call: Callable[[Screens], Awaitable[int | None]]) -> int | None:
    """`call` on the Screens record; None, logged, when it cannot be reached."""
    try:
        return await call(services.get(Screens))
    except ScreensUnavailable:
        logs.warning(log, "live.screens_unavailable")
        return None


def frame(got: Event | Resync) -> bytes:
    """One event as its `data:` line."""
    return b"data: " + wire(got).model_dump_json().encode() + b"\n\n"


def wire(got: Event | Resync) -> LiveEvent:
    if isinstance(got, Resync):
        return LiveEvent(LiveResync(type="resync"))
    if isinstance(got, HerState):
        return LiveEvent(LiveState(type="state", turn=got.turn, state=got.state, at_most_s=got.at_most_s))
    if isinstance(got, BenchChanged):
        return LiveEvent(LiveBench(type="bench", bench_id=got.bench_id, seq=got.seq))
    if isinstance(got, BenchCued):
        return LiveEvent(LiveCue(type="cue", bench_id=got.bench_id, piece_id=got.piece_id, action=got.action,
                                 seconds=got.seconds))
    if isinstance(got, ScreenChanged):
        return LiveEvent(LiveScreen(type="screen", device_id=got.device_id, seq=got.seq))
    if isinstance(got, PageMoved):
        return LiveEvent(LivePage(type="page", room=got.room, bench_id=got.bench_id))
    if isinstance(got, TurnFailed):
        return LiveEvent(LiveFailed(type="failed", thread=got.thread, why=got.why))
    return LiveEvent(LiveTurn(type="turn", thread=got.thread))
