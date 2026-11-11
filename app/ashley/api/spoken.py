"""Tap to talk: a page sends one utterance as a WAV of 16 kHz 16-bit mono PCM (`audio/wav`) and gets back what was
heard, which it then sends as a typed message on its own route, so a spoken turn is a typed one: the same thread, the
same `Inbound`, her reply in text. A signed-in person uses `POST /api/chat/transcripts` (`person.person_speaking`), the
kiosk `POST /api/kiosk/transcripts` (`kiosk_device.kiosk_speaking`, refused through the public tunnel like every kiosk
route, and counted against the device's rate since a transcription is paid for).

A body over the cap (`channels/spoken.json`, served by `GET /api/spoken/limits`) is refused 413 `too_large` before or
while it is read; one that is not that WAV is 415 `unsupported`. The audio is held in memory for the one transcription
and never stored. Logs `spoken.heard` with the person or device id, the bytes, the audio's duration, how long the
transcription took and the transcript's length; never the audio or the words."""

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import logs
from ..channels import spoken
from ..channels.voice import config as voice_config
from .kiosk_device import KioskSpeaking, counted
from .models import ErrorResponse
from .spoken_models import SpokenLimits, Transcript
from .person import Speaking

router = APIRouter()
log = logging.getLogger("ashley.api.spoken")
CAPS = spoken.load()
END_OF_SPEECH = voice_config.load().end_of_speech
_BODY: dict[str, Any] = {"requestBody": {"required": True, "description": "One utterance: a WAV of 16 kHz 16-bit "
                                         "mono PCM, at most `SpokenLimits.max_ms` long",
                                         "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}}
_HEARD: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`"},
    403: {"model": ErrorResponse, "description": "`forbidden`: from another site, or not `audio/wav`"},
    413: {"model": ErrorResponse, "description": "`too_large`: longer than `SpokenLimits.max_ms`"},
    415: {"model": ErrorResponse, "description": "`unsupported`: not a WAV of 16 kHz 16-bit mono PCM"},
    503: {"model": ErrorResponse, "description": "`unavailable`: nothing could transcribe it"}}

class _TooLarge(Exception):
    pass


@router.get("/api/spoken/limits", response_model=SpokenLimits)
async def spoken_limits() -> SpokenLimits:
    """200 `SpokenLimits`. Needs no sign-in: it says only how long an utterance may be, when it has ended, and how long
    her answer to it can be fetched."""
    return SpokenLimits(max_ms=CAPS.max_ms, speech_ms=END_OF_SPEECH.speech_ms, silence_ms=END_OF_SPEECH.silence_ms,
                        quiet_rms=CAPS.quiet_rms, voice_s=CAPS.voice_s)


@router.post("/api/chat/transcripts", response_model=Transcript, responses=_HEARD, openapi_extra=_BODY)
async def chat_transcript(signed_in: Speaking, request: Request) -> Transcript | JSONResponse:
    """200 `Transcript`; 401 `unauthorized`; 403 `forbidden`; 413 `too_large`; 415 `unsupported`; 503
    `unavailable`."""
    return await _heard(request, signed_in.person.household_id, {"person": signed_in.person.id})


@router.post("/api/kiosk/transcripts", response_model=Transcript, openapi_extra=_BODY, responses={
    **_HEARD, 401: {"model": ErrorResponse, "description": "`unauthorized`: not paired, a revoked device, or from the "
                    "public internet"},
    429: {"model": ErrorResponse, "description": "`rate_limited`: the device is over its rate"}})
async def kiosk_transcript(device: KioskSpeaking, request: Request) -> Transcript | JSONResponse:
    """200 `Transcript`; 401 `unauthorized`; 403 `forbidden`; 413 `too_large`; 415 `unsupported`; 429
    `rate_limited`; 503 `unavailable`."""
    await counted(device)
    return await _heard(request, device.household_id, {"device": device.id})


async def _heard(request: Request, household_id: int, who: dict[str, int]) -> Transcript | JSONResponse:
    started = time.perf_counter()
    size, audio_ms, outcome, words = 0, None, "unavailable", ""
    try:
        wav = await _body(request)
        size = len(wav)
        pcm = spoken.pcm_of(wav, CAPS)
        audio_ms = spoken.FORMAT.duration_ms(len(pcm))
        words = await spoken.words_in(pcm, household_id)
        outcome = "heard" if words else "empty"
        return Transcript(text=words)
    except (_TooLarge, spoken.TooLong):
        outcome = "too_large"
        return _error(413, "too_large", "that was too long to hear; say it in under %d seconds" % (CAPS.max_ms // 1000))
    except spoken.Unsupported:
        outcome = "unsupported"
        return _error(415, "unsupported", "send a WAV of 16 kHz 16-bit mono PCM")
    except spoken.SpokenUnavailable:
        return _error(503, "unavailable", "she cannot listen right now; try again shortly")
    finally:
        logs.info(log, "spoken.heard", **who, outcome=outcome, bytes=size, audio_ms=audio_ms,
                  ms=int((time.perf_counter() - started) * 1000), chars=len(words))


async def _body(request: Request) -> bytes:
    """The body, refused as soon as it is known to pass `CAPS.max_bytes`. Raises _TooLarge."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > CAPS.max_bytes:
        raise _TooLarge()
    read = bytearray()
    async for chunk in request.stream():
        read += chunk
        if len(read) > CAPS.max_bytes:
            raise _TooLarge()
    return bytes(read)


def _error(status: int, code: Literal["too_large", "unsupported", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())
