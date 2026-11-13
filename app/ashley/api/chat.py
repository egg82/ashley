"""Web chat, a channel adapter for a signed-in person (`person.person_signed_in`; a write is same-origin JSON). Their
thread is `person:<id>:web`: personal, so the speaker is the person, the audience `owner` and no place; a `chat`
conversation, in text. A reply that only says she will check comes back with `follows`; the answer is stored as her
turn, and every page open on the thread learns of it from `GET /api/live` and reads the conversation back, so two tabs
both show it. Nothing of the thread waits in the `Outbox`. A pasted block (`ChatMessage.attachment`) is the turn's
`Inbound.attachment`, and over the threshold the turn starts `pasted` (`channels.pasted`)."""

import logging
from dataclasses import replace
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels import pasted, unprompted
from ..channels.agree import AgreeRefusal, AgreeRefused, AgreeUnavailable, agree, waiting
from ..channels.model import Inbound
from ..channels.respond import RespondRefused, RespondUnavailable, respond
from ..connections.deployment_secrets import DeploymentSecrets
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..conversations.inflight import InFlight, InFlightUnavailable
from ..conversations.model import Attachment, Turn
from ..looks.looks import Look, Looks, LooksUnavailable
from ..runs.runs import Runs, RunsUnavailable
from ..signin.model import SignedIn
from . import chat_looks
from .chat_runs import under_answers
from .chat_models import ChatAttachment, ChatMessage, ChatRequest
from .receipt_models import wire_agreed, wire_receipts
from .models import AgreeReply, AgreeRequest, ChatConversation, ChatConversationTurn, ChatReply, ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: a system her reply needs could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site, or not JSON"}}


_AGREE_DETAIL: dict[AgreeRefusal, str] = {
    "gone": "there is nothing waiting for your OK any more",
    "expired": "that was held too long ago to agree to now",
    "not_yours": "that was not held for you"}


def thread_of(signed_in: SignedIn) -> str:
    return f"person:{signed_in.person.id}:web"


def inbound_from(signed_in: SignedIn, body: ChatRequest) -> Inbound:
    """The message as the turn loop takes it: the person's own thread, so they are the speaker and its only audience;
    tagged `said_aloud` when it is a `ChatMessage` that says so."""
    who = signed_in.person
    return Inbound(household_id=who.household_id, thread=thread_of(signed_in), text=body.text, kind="chat",
                   medium="text", audience="owner", speaker_id=who.id, shared=False, place=None, channel="web",
                   later=True, later_by="turn", opens_benches=True, on_page=True, taint=None,
                   said_aloud=isinstance(body, ChatMessage) and body.said_aloud)


def agree_inbound(signed_in: SignedIn, body: AgreeRequest) -> Inbound:
    """The tap as the turn loop takes it: on the person's own thread like their message, with no text and the proposal
    named in `agree`."""
    who = signed_in.person
    return Inbound(household_id=who.household_id, thread=thread_of(signed_in), text="", kind="chat", medium="text",
                   audience="owner", speaker_id=who.id, shared=False, place=None, channel="web", later=True,
                   later_by="turn", on_page=True, taint=None, agree=body.proposal_id)


def wire_attachment(attachment: Attachment | None) -> ChatAttachment | None:
    return None if attachment is None else ChatAttachment(title=attachment.title, text=attachment.text)


def _error(status: int, code: Literal["refused", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "she cannot answer right now; try again shortly")


@router.post("/api/chat/messages", response_model=ChatReply, responses={
    **_WRITE, 422: {"model": ErrorResponse, "description": "`refused`; a body outside `ChatMessage` gets FastAPI's "
                    "own validation error instead, which is not this schema"}})
async def send(signed_in: Person, body: ChatMessage) -> ChatReply | JSONResponse:
    """200 `ChatReply`; 401 `unauthorized`; 403 `forbidden`; 422 `refused` when she declined, or FastAPI's validation
    error for a body outside `ChatMessage`; 503 `unavailable`."""
    attached = None if body.attachment is None else Attachment(body.attachment.title, body.attachment.text)
    return await answer(replace(inbound_from(signed_in, body), attachment=attached, taint=pasted.taint_of(attached)))


@router.post("/api/chat/agree", response_model=AgreeReply, responses={
    **_WRITE, 409: {"model": ErrorResponse, "description": "`gone`, `expired` or `not_yours`: the proposal cannot be "
                    "agreed to; nothing was done"},
    422: {"model": ErrorResponse, "description": "FastAPI's own validation error for a body outside `AgreeRequest`, "
          "which is not this schema"}})
async def agree_to(signed_in: Person, body: AgreeRequest) -> AgreeReply | JSONResponse:
    """200 `AgreeReply`, the held calls carried out and what became of each; 401 `unauthorized`; 403 `forbidden`;
    409 `gone` (carried out already, replaced by a later hold, or never held), `expired` or `not_yours` (held for
    another person); 503 `unavailable`. No model is asked."""
    try:
        done = await agree(agree_inbound(signed_in, body))
    except AgreeRefused as e:
        return JSONResponse(status_code=409, content=ErrorResponse(code=e.reason, detail=_AGREE_DETAIL[e.reason]).model_dump())
    except AgreeUnavailable:
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="that could not be carried out right now; try again shortly").model_dump())
    return AgreeReply(conversation_id=done.conversation_id, agreed=wire_agreed(done.outcome))


async def answer(inbound: Inbound) -> ChatReply | JSONResponse:
    """Her reply to a message on a web thread, or 422 `refused` / 503 `unavailable`."""
    try:
        out = await respond(inbound)
    except RespondRefused:
        return _error(422, "refused", "she declined to answer that")
    except RespondUnavailable:
        return _unavailable()
    return ChatReply(conversation_id=out.conversation_id, body=out.body, follows=out.follows,
                     receipts=wire_receipts(out.receipts))


def agree_on(turn: Turn, held: tuple[int, int] | None) -> int | None:
    """The proposal `held` (its id and the turn it was held in) on her final answer to that turn, where its held receipt is."""
    if held is None or turn.author != "ashley" or turn.follows or turn.answers != held[1]:
        return None
    return held[0]


async def _looks(household_id: int, conversation_id: int) -> list[Look]:
    """The conversation's looks; none, logged `chat.looks_unavailable`, when the record cannot be read: the
    pictures are an addition to the turns, which are still worth showing."""
    try:
        return await services.get(Looks).in_conversation(household_id, conversation_id)
    except LooksUnavailable:
        logs.warning(log, "chat.looks_unavailable", conversation=conversation_id)
        return []


@router.get("/api/chat/conversation", response_model=ChatConversation, responses=_SIGNED_IN)
async def conversation(signed_in: Person, request: Request) -> ChatConversation | JSONResponse:
    """200 `ChatConversation`; 401 `unauthorized`; 503 `unavailable`."""
    person = signed_in.person
    return await conversation_on(person.household_id, thread_of(signed_in), request,
                                 await waiting(person.id, person.household_id))


async def conversation_on(household_id: int, thread: str, request: Request,
                          held: tuple[int, int] | None = None) -> ChatConversation | JSONResponse:
    """The open conversation on a web thread of the household, with the code runs and looks under her answers and the
    turns she is still working on, or 503 `unavailable`. The looks' links are minted under the app's link key. `held` is
    the proposal the person can agree to and the turn it was held in (`channels.agree.waiting`)."""
    try:
        found = await services.get(Conversations).on_thread(household_id, thread)
        if found is None or found.state == "closed":
            return ChatConversation(thread=thread, conversation_id=None, started_at=None, turns=[])
        runs = await services.get(Runs).in_conversation(household_id, found.id)
        looked = await _looks(household_id, found.id)
        working = await services.get(InFlight).working(found.id)
    except (ConversationsUnavailable, RunsUnavailable, InFlightUnavailable):
        return _unavailable()
    shown = under_answers(found.turns, runs)
    seen = chat_looks.under_answers(found.turns, looked, services.get(DeploymentSecrets).link_key().encode())
    turns = [ChatConversationTurn(id=t.id, author=t.author, text=t.text, at=t.at, follows=t.follows,
                                  continued_on=t.continued_on, attachment=wire_attachment(t.attachment),
                                  runs=shown.get(t.id, []), looks=seen.get(t.id, []), working=t.id in working,
                                  agree=agree_on(t, held), voiced=t.spoken is not None,
                                  receipts=wire_receipts(t.receipts), 
                                  agreed=None if t.agreed is None else wire_agreed(t.agreed))
             for t in unprompted.shown(found.turns)]
    return ChatConversation(thread=thread, conversation_id=found.id, started_at=found.started_at,
                            turns=turns)
