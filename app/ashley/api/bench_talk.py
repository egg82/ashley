"""A bench's talk: a conversation whose thread is the bench's, `bench:<id>`, carried by the shared turn loop as web chat
is (`api.chat`): the owner is the speaker and its only audience, a `brainstorm` conversation, in text, and a held answer
is stored as her turn and announced on `GET /api/live` as a `LiveTurn` for the bench's thread. Only the bench's owner
talks on it or reads it back; anyone else's bench id is 404 `not_found`."""

from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .. import services
from ..channels.model import Inbound, on_bench
from ..workshop.model import Bench, Piece
from ..workshop.workshop import BenchNotFound, BenchView, Workshop, WorkshopUnavailable
from .benches import not_found, owner_of, unavailable
from .chat import answer, conversation_on
from .history import history_page
from .history_models import PastHistory
from .chat_models import BenchMessage, ChatRequest
from .models import ChatConversation, ChatReply, ErrorResponse
from .person import Person

router = APIRouter()
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    404: {"model": ErrorResponse, "description": "`not_found`: no bench of this person's has that id"},
    503: {"model": ErrorResponse, "description": "`unavailable`: a system her reply needs could not be reached"},
    422: {"model": ErrorResponse, "description": "`refused`; a path or body outside its model gets FastAPI's own "
          "validation error instead, which is not this schema"}}


def inbound_for(signed_in: Person, bench_id: int, body: ChatRequest, pasted: Piece | None = None) -> Inbound:
    """The message as the turn loop takes it: on the bench's thread, the owner the speaker and its only audience. A
    `pasted` piece is told to her with the message, in its `note`, which is never stored."""
    who = signed_in.person
    got = on_bench(who.household_id, who.id, bench_id, body.text)
    if pasted is None:
        return got
    note = (f'[They pasted a long text with this message. It is on the bench now as piece {pasted.id}, '
            f'"{pasted.text.title}"; read it with bench_read_piece.]')
    return replace(got, note=note)


async def _owned(signed_in: Person, bench_id: int) -> Bench | JSONResponse:
    found = await _read(signed_in, bench_id)
    return found if isinstance(found, JSONResponse) else found.bench


async def _read(signed_in: Person, bench_id: int) -> BenchView | JSONResponse:
    try:
        return await services.get(Workshop).read(owner_of(signed_in), bench_id)
    except BenchNotFound:
        return not_found()
    except WorkshopUnavailable:
        return unavailable()


@router.post("/api/benches/{bench_id}/messages", response_model=ChatReply, responses={
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site, or not JSON"},
    410: {"model": ErrorResponse, "description": "`closed`: the bench is closed"}})
async def send_on_bench(signed_in: Person, bench_id: int, body: BenchMessage) -> ChatReply | JSONResponse:
    """200 `ChatReply`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 410 `closed`; 422 `refused` when she
    declined or `piece_id` is not a piece on the bench; 503 `unavailable`."""
    view = await _read(signed_in, bench_id)
    if isinstance(view, JSONResponse):
        return view
    if view.bench.closed_at is not None:
        return JSONResponse(status_code=410, content=ErrorResponse(code="closed", detail="the bench is closed").model_dump())
    pasted = None
    if body.piece_id is not None:
        pasted = next((p for p in view.pieces if p.id == body.piece_id), None)
        if pasted is None:
            return JSONResponse(status_code=422, content=ErrorResponse(
                code="refused", detail="that piece is not on this bench").model_dump())
    return await answer(inbound_for(signed_in, bench_id, body, pasted))


@router.get("/api/benches/{bench_id}/conversation", response_model=ChatConversation, responses=_READ)
async def bench_conversation(signed_in: Person, bench_id: int, request: Request) -> ChatConversation | JSONResponse:
    """200 `ChatConversation` of the bench's thread; 401 `unauthorized`; 404 `not_found`; 503 `unavailable`."""
    bench = await _owned(signed_in, bench_id)
    if isinstance(bench, JSONResponse):
        return bench
    return await conversation_on(signed_in.person.household_id, bench.thread, request)


@router.get("/api/benches/{bench_id}/conversations", response_model=PastHistory, responses={
    **_READ, 422: {"model": ErrorResponse, "description": "`refused`: `before` is not one a page returned"}})
async def bench_history(signed_in: Person, bench_id: int, limit: Annotated[int, Query(ge=1, le=50)] = 10,
                        before: Annotated[str | None, Query(max_length=64)] = None) -> PastHistory | JSONResponse:
    """200 `PastHistory` of every conversation on the bench's thread, closed ones too, paged as `GET
    /api/chat/conversations` is and read one by one from `GET /api/chat/conversations/{id}`; 401 `unauthorized`; 404
    `not_found`; 422 `refused`; 503 `unavailable`."""
    bench = await _owned(signed_in, bench_id)
    if isinstance(bench, JSONResponse):
        return bench
    return await history_page(signed_in.person, limit, before, bench.thread)
