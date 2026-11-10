"""`GET /api/voice/clips/{token}`: her spoken reply for a satellite or room speaker to play, synthesised as it is
fetched (`Inference.speak`) and streamed as the provider produces it. The token in the URL is the only credential (a
media player cannot send a header); it is random, short-lived (`voice.json`, `clip_retention_s`) and never logged.

Logs `voice.clip` per fetch that started streaming: clip and device ids, `tts_provider` and `tts_model` (the route
that spoke), `tts_first_byte_ms` (request to the first
audio byte), `total_ms` (the wake to that byte, by the database's clock and then this process's), bytes sent, and
whether the stream ended `complete`."""

import time
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..channels.voice import playback
from .models import ErrorResponse
from .voice_stream import timed

router = APIRouter()


# The token is read from the path rather than taken as a parameter, so FastAPI declares no 422: any string is a token,
# and one that names no clip is 404. The parameter is declared by hand instead.
_TOKEN = {"name": "token", "in": "path", "required": True, "schema": {"type": "string"},
          "description": "The token in the URL her run sent the device"}


@router.get("/api/voice/clips/{token}", response_class=StreamingResponse, response_model=None,
            openapi_extra={"parameters": [_TOKEN]}, responses={
                200: {"content": {"audio/mpeg": {}, "audio/wav": {}},
                      "description": "Her voice; the media type is the speech's"},
                404: {"model": ErrorResponse},
                503: {"model": ErrorResponse},
            })
async def get_voice_clip(request: Request) -> StreamingResponse | JSONResponse:
    """200 the audio; 404 `not_found` for a token that names no clip or an expired one; 503 `unavailable` when the
    clip could not be read or no speech route started."""
    asked = time.perf_counter()
    try:
        found = await playback.speech_for(request.path_params["token"])
    except playback.PlaybackUnavailable:
        return _error(503, "unavailable", "try again shortly")
    if found is None:
        return _error(404, "not_found", "no such clip")
    clip, speech = found
    return StreamingResponse(timed(speech.chunks, asked, speech.provider, speech.model, "voice.clip",
                                   {"clip": clip.id, "device": clip.device_id}, clip.since_wake_ms),
                             media_type=speech.media_type)


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())
