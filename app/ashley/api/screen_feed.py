"""A camera's live feed on a screen, for a person's page (`/api/screens/feed`) and the kiosk (`/api/kiosk/feed`), the same
four routes for each, by the token the page opened its live feed under (`GET /api/live?screen=`):

- `GET ?screen=` reads the feed this screen shows (`ScreenFeedRead`), or none.
- `DELETE ?screen=` takes it off this screen: the page's swipe.
- `POST /offer` relays the page's WebRTC offer to the camera through her, and streams the camera's session, answer and
  candidates back as Server-Sent Events (`FeedSignal`). The media goes from the camera to the page; her connection to the
  camera's service stays open exactly as long as the stream, since the service ends the feed when it closes, and the stream
  ends when the feed's time is up. A stream that cannot start, or ends early, carries an `error` signal.
- `POST /candidate` relays one of the page's candidates for the session.

Only the camera the screen is shown, and only while it is one the household lets her look through, can be asked for: a page
never names a camera. The camera service's credentials never reach a page. Logs `screen.feed` with the person or device id,
the route and the outcome, and `screen.feed_ended` with the duration; never an offer, an answer, a candidate or a camera."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from .. import logs
from ..channels.kiosk import feed
from ..channels.kiosk.feed import FeedRefused, NotShowing, Owner
from ..live.screens import ScreensUnavailable
from .kiosk_device import Kiosk
from .live import CONFIG, HEARTBEAT, EventStream
from .models import ErrorResponse
from .person import Person
from .screen_feed_models import FeedCandidate, FeedOffer, FeedSignal, ScreenFeed, ScreenFeedRead
from .screens import unavailable

log = logging.getLogger("ashley.api.screen_feed")
_JSON_ERROR = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session, or not a paired device"},
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site or was not JSON"},
    404: {"model": ErrorResponse, "description": "`not_found`: this screen shows no feed, or its camera is no longer one "
                                                 "she may show or gives no live video"},
    422: {"description": "FastAPI's validation error: a `screen` that is not a UUID, or a body outside its model"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the open screens, or the camera's service, cannot be "
                                                 "reached"}}
_OFFER_ERRORS: dict[int | str, dict[str, Any]] = {
    **_ERRORS, 200: {"model": FeedSignal, "description": "A stream of `FeedSignal`, one per `data:` line",
                     "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/FeedSignal"}}}}}
Owned = Callable[..., Awaitable[Owner]]


async def person_owner(signed_in: Person) -> Owner:
    who = signed_in.person
    return Owner(who.household_id, who.id, None)


async def kiosk_owner(device: Kiosk) -> Owner:
    return Owner(device.household_id, None, device.id)


def _now() -> datetime:
    return datetime.now(UTC)


def _refused(reason: str) -> JSONResponse:
    if reason in ("not_connected", "unavailable"):
        return unavailable()
    return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail="no live feed here").model_dump())


def _owner_id(who: Owner) -> dict[str, int]:
    return {"person": who.person_id} if who.person_id is not None else {"device": who.device_id or 0}


def routes(prefix: str, owner_of: Owned, owner: str) -> APIRouter:
    """The four routes under `prefix` for the owner `owner_of` signs in; `owner` names them in the contract."""
    router = APIRouter(prefix=prefix)

    @router.get("", operation_id=f"{owner}_feed_read", response_model=ScreenFeedRead, responses={k: v for k, v in _ERRORS.items() if k in (401, 422, 503)})
    async def read(who: Annotated[Owner, Depends(owner_of)], screen: UUID) -> ScreenFeedRead | JSONResponse:
        """200 `ScreenFeedRead`, the feed this screen shows now (null when none); 401 `unauthorized`; 422 FastAPI's
        validation error; 503 `unavailable`."""
        try:
            showing = await feed.current(who, str(screen), _now())
        except NotShowing:
            return ScreenFeedRead(feed=None)
        except (ScreensUnavailable, FeedRefused):
            return unavailable()
        logs.info(log, "screen.feed", route="read", outcome="showing", **_owner_id(who))
        return ScreenFeedRead(feed=ScreenFeed.model_validate({
            "camera_title": showing.title, "remaining_s": showing.remaining_s, **showing.config}))

    @router.delete("", operation_id=f"{owner}_feed_dismiss", status_code=204, response_class=Response, responses={
        k: v for k, v in _ERRORS.items() if k in (401, 403, 422, 503)})
    async def dismiss(who: Annotated[Owner, Depends(owner_of)], screen: UUID) -> Response:
        """204, the feed taken off this screen; 401 `unauthorized`; 403 `forbidden`; 422 FastAPI's validation error; 503
        `unavailable`."""
        try:
            await feed.dismiss(who, str(screen))
        except ScreensUnavailable:
            return unavailable()
        logs.info(log, "screen.feed", route="dismiss", outcome="ok", **_owner_id(who))
        return Response(status_code=204)

    @router.post("/offer", operation_id=f"{owner}_feed_offer", response_class=EventStream, response_model=None, responses=_OFFER_ERRORS)
    async def offer(who: Annotated[Owner, Depends(owner_of)], body: FeedOffer) -> Response:
        """200 a stream of `FeedSignal` (an `error` signal ends one that failed); 401 `unauthorized`; 403 `forbidden`; 404
        `not_found`; 422 FastAPI's validation error; 503 `unavailable`."""
        try:
            await feed.check(who, str(body.screen), _now())
        except NotShowing:
            return _refused("no_such_camera")
        except FeedRefused as e:
            return _refused(e.reason)
        except ScreensUnavailable:
            return unavailable()
        return EventStream(_stream(who, str(body.screen), body.offer),
                           headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/candidate", operation_id=f"{owner}_feed_candidate", status_code=204, response_class=Response, responses=_ERRORS)
    async def candidate(who: Annotated[Owner, Depends(owner_of)], body: FeedCandidate) -> Response:
        """204, the candidate handed to the camera's service; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422
        FastAPI's validation error; 503 `unavailable`."""
        try:
            await feed.candidate(who, str(body.screen), _now(), body.session_id, body.candidate, body.sdp_mid,
                                 body.sdp_m_line_index, body.username_fragment)
        except NotShowing:
            return _refused("no_such_camera")
        except FeedRefused as e:
            return _refused(e.reason)
        except ScreensUnavailable:
            return unavailable()
        return Response(status_code=204)

    return router


router = APIRouter()
router.include_router(routes("/api/screens/feed", person_owner, "screen"))
router.include_router(routes("/api/kiosk/feed", kiosk_owner, "kiosk"))


def _frame(signal: dict[str, object]) -> bytes:
    return b"data: " + FeedSignal.model_validate(signal).model_dump_json().encode() + b"\n\n"


async def _stream(who: Owner, token: str, offer: str) -> AsyncIterator[bytes]:
    """The offer's signals as `data:` lines, with a comment between them often enough that nothing idle closes the stream.
    The relay lives in its own task, so it opens and closes its connection to the camera's service in one task."""
    began = time.monotonic()
    queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
    pump = asyncio.create_task(_pump(who, token, offer, queue))
    try:
        while True:
            try:
                got = await asyncio.wait_for(queue.get(), CONFIG.heartbeat_s)
            except TimeoutError:
                yield HEARTBEAT
                continue
            if got is None:
                break
            yield _frame(got)
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        logs.info(log, "screen.feed_ended", duration_ms=int((time.monotonic() - began) * 1000), **_owner_id(who))


async def _pump(who: Owner, token: str, offer: str, queue: asyncio.Queue[dict[str, object] | None]) -> None:
    outcome = "ended"
    try:
        async with feed.relay(who, token, offer, _now()) as (left, signals):
            async with asyncio.timeout(left):
                async for signal in signals:
                    queue.put_nowait(signal)
    except TimeoutError:
        outcome = "time_up"
    except (NotShowing, FeedRefused, ScreensUnavailable) as e:
        outcome = e.reason if isinstance(e, FeedRefused) else type(e).__name__
        queue.put_nowait({"type": "error", "code": "unavailable"})
    except Exception as e:
        outcome = type(e).__name__
        logs.error(log, "screen.feed_failed", exc=True)
        queue.put_nowait({"type": "error", "code": "unavailable"})
    finally:
        logs.info(log, "screen.feed", route="offer", outcome=outcome, **_owner_id(who))
        queue.put_nowait(None)
