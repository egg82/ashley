"""A signed-in person's Claude Code session as a session piece shows it (`ashley.workshop.session_piece`): the end of its
screen, read from the person's own herdr bridge each time it is asked for, and how soon to ask again. The page asks
while the piece is on screen, so a session nobody is looking at costs nothing. Nothing is kept between asks: any pod on
either site answers the same, and the bridge is the only state. The screen is never stored or logged; a `claude.screen`
line is logged only for an answer that is not `live`, with its state and the bridge's reason."""

import asyncio
import hashlib
import logging
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict

from .. import logs, services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..herdr import config
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed, Reason, Status
from ..workshop.session_piece import SESSION_ID
from .models import ErrorResponse
from .person import Person

router = APIRouter()
CONFIG = config.load()
log = logging.getLogger("ashley.api")
State = Literal["live", "gone", "not_connected", "unreachable", "refused"]
_REFUSED: tuple[Reason, ...] = ("bad_token", "wrong_person", "pin_mismatch", "unexpected")
_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    422: {"model": ErrorResponse, "description": "a session id that is not one gets FastAPI's own validation error, "
          "which is not this schema"}}


class SessionScreen(BaseModel):
    """A session's screen as it is now. `state`: `live` (shown below), `gone` (the bridge lists no such session: it
    ended or was closed), `not_connected` (the person has no herdr bridge), `unreachable` (the bridge, herdr or the
    person's connections did not answer) or `refused` (the bridge turned the connection away: its token, person or
    certificate). While `live`, `status` is the session's (`idle`, `working`, `blocked`, `done` or `unknown`),
    `digest` names the screen's text (a hash, the same for the same text), and `text` is its last lines as unwrapped
    text, null when `digest` is the one the page asked with (nothing changed); `truncated` says older lines were left
    out. `again_ms`: how long the page waits before it asks again."""

    model_config = ConfigDict(extra="forbid")

    state: State
    status: Status | None = None
    digest: str | None = None
    text: str | None = None
    truncated: bool = False
    again_ms: int


@router.get("/api/claude/sessions/{session_id}/screen", response_model=SessionScreen, responses=_ERRORS)
async def session_screen(signed_in: Person, session_id: Annotated[str, PathParam(pattern=SESSION_ID.pattern)],
                         seen: str | None = None) -> SessionScreen:
    """200 `SessionScreen`, whatever the bridge answered; 401 `unauthorized`; 422 for an id that is not a session's.
    `seen` is the `digest` of the screen the page shows, so an unchanged screen is not sent again. (The bridge's own
    `revision` is herdr's count of changes to the agent, not to its screen, so it cannot say that.)"""
    started = time.monotonic()
    person = signed_in.person
    try:
        opened = await ports.opened(services.get(Connections), "herdr", person.household_id, person.id)
        if opened is None:
            return _not_live("not_connected", None, started)
        access = Access.of(opened.connection.base_url, opened.secret, person.id)
        bridge = services.get(Bridge)
        listed, screen = await asyncio.gather(bridge.sessions(access),
                                              bridge.read(access, session_id, CONFIG.screen_lines))
    except ConnectionsUnavailable:
        return _not_live("unreachable", None, started)
    except BridgeFailed as e:
        state: State = "gone" if e.reason == "not_found" else "refused" if e.reason in _REFUSED else "unreachable"
        return _not_live(state, e.reason, started)
    session = next((s for s in listed.sessions if s.id == session_id), None)
    if session is None:
        return _not_live("gone", None, started)
    again = CONFIG.screen_working_s if session.status == "working" else CONFIG.screen_still_s
    digest = hashlib.sha256(screen.text.encode()).hexdigest()[:16]
    return SessionScreen(state="live", status=session.status, digest=digest, text=None if seen == digest else screen.text,
                         truncated=screen.truncated, again_ms=int(again * 1000))


def _not_live(state: State, reason: Reason | None, started: float) -> SessionScreen:
    logs.info(log, "claude.screen", state=state, reason=reason, duration_ms=int((time.monotonic() - started) * 1000))
    away = CONFIG.screen_away_s if state in ("unreachable", "refused") else CONFIG.screen_still_s
    return SessionScreen(state=state, again_ms=int(away * 1000))
