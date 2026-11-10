"""`GET /api/chat/turns/{turn_id}/voice` and `GET /api/kiosk/turns/{turn_id}/voice`: what she chose to say aloud with a
turn (`channels.aloud`), synthesised as it is fetched and streamed as the provider produces it. The caller's own
credential decides: a person's session for their web thread, the device cookie for the kiosk's, so a turn on any other
thread is a 404, the same as one with no voice or one older than `voice_s` (`channels/spoken.json`); no route confirms
that another's turn exists.

Logs `voice.turn` per fetch that started streaming: the turn id, `by` (`person` or `device`) and that id, `tts_provider`
and `tts_model`, `tts_first_byte_ms`, bytes sent and whether the stream ended `complete`. Never the text."""

import time
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..channels import aloud
from . import chat, kiosk
from .kiosk_device import Kiosk
from .models import ErrorResponse
from .person import Person
from .voice_stream import timed

router = APIRouter()
_VOICE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"audio/mpeg": {}, "audio/wav": {}}, "description": "Her voice; the media type is the speech's"},
    401: {"model": ErrorResponse, "description": "`unauthorized`"},
    404: {"model": ErrorResponse, "description": "`not_found`: not a turn of this thread with a voice, or past `voice_s`"},
    422: {"model": ErrorResponse, "description": "a non-integer turn id gets FastAPI's own validation error, which is not "
                                                 "this schema"},
    503: {"model": ErrorResponse, "description": "`unavailable`"}}


@router.get("/api/chat/turns/{turn_id}/voice", response_class=StreamingResponse, response_model=None, responses=_VOICE)
async def chat_turn_voice(turn_id: int, signed_in: Person) -> StreamingResponse | JSONResponse:
    """200 the audio; 401 `unauthorized`; 404 `not_found`; 422 FastAPI's validation error for a non-integer id; 503
    `unavailable`."""
    return await _voice(signed_in.person.household_id, chat.thread_of(signed_in), turn_id, "person", signed_in.person.id)


@router.get("/api/kiosk/turns/{turn_id}/voice", response_class=StreamingResponse, response_model=None, responses=_VOICE)
async def kiosk_turn_voice(turn_id: int, device: Kiosk) -> StreamingResponse | JSONResponse:
    """200 the audio; 401 `unauthorized`; 404 `not_found`; 422 FastAPI's validation error for a non-integer id; 503
    `unavailable`."""
    return await _voice(device.household_id, kiosk.thread_of(device), turn_id, "device", device.id)


async def _voice(household_id: int, thread: str, turn_id: int, by: Literal["person", "device"],
                 caller: int) -> StreamingResponse | JSONResponse:
    asked = time.perf_counter()
    try:
        speech = await aloud.speech_of(household_id, thread, turn_id)
    except aloud.AloudUnavailable:
        return _error(503, "unavailable", "try again shortly")
    if speech is None:
        return _error(404, "not_found", "no such voice")
    return StreamingResponse(timed(speech.chunks, asked, speech.provider, speech.model, "voice.turn",
                                   {"turn": turn_id, "by": by, by: caller}), media_type=speech.media_type)


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())
