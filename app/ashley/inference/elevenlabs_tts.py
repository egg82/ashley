"""`ElevenLabsSpeaker`: text to speech through ElevenLabs' streaming endpoint,
`POST /v1/text-to-speech/{voice_id}/stream`. It takes a configured long-lived `httpx2.AsyncClient` (base URL, `xi-api-key` header), so connections stay warm and a
test can point it at a stand-in server.

Route `model` is ElevenLabs' `model_id` (a low-latency one such as `eleven_flash_v2_5`). Params: `voice_id`
(non-empty string, required) and `output_format` (an `mp3_...` format, default `mp3_44100_128`, or a `pcm_<rate>`
format). An mp3 stream is `audio/mpeg`; a `pcm_<rate>` stream is `audio/wav`: a 44-byte RIFF header for 16-bit mono PCM
at that rate, then the PCM as it arrives. The length is unknown while streaming, so the RIFF and data sizes are
0xFFFFFFFF, "unknown", as an unseekable WAV writer leaves them. `timeout_s` bounds connecting and the wait for each part of the response, so the first bytes must arrive
within it. A timeout, connection failure, 408, 409, 429, 5xx, 401, 402 or 403 fails `unavailable`; any other status
`error`; a response with no audio `invalid_output`. `warm` sends `HEAD /`, which is not billed and whatever its status
leaves a connection in the client's pool; it fails `unavailable` only when the connection could not be made."""

import re
import struct
from collections.abc import AsyncIterator, Mapping
from urllib.parse import quote

import httpx2

from .provider import ProviderFailed, status_failure
from .speech_provider import Speaker, SpeechStream

_FORMAT = re.compile(r"mp3_\d+_\d+|pcm_(\d+)")
_DEFAULT_FORMAT = "mp3_44100_128"


class ElevenLabsSpeaker(Speaker):
    def __init__(self, name: str, client: httpx2.AsyncClient) -> None:
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def check_speak_params(self, params: Mapping[str, object]) -> None:
        unknown = sorted(set(params) - {"voice_id", "output_format"})
        if unknown:
            raise ValueError(f"unknown parameter {unknown[0]!r}")
        voice = params.get("voice_id")
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError("voice_id is required and must be a non-empty string")
        output_format = params.get("output_format", _DEFAULT_FORMAT)
        if not isinstance(output_format, str) or not _FORMAT.fullmatch(output_format):
            raise ValueError("output_format must be an mp3 format such as mp3_44100_128, or pcm_<rate>")

    async def warm(self, timeout_s: float) -> None:
        try:
            await self._client.head("/", timeout=timeout_s)
        except httpx2.HTTPError as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e

    async def speak(self, model: str, params: Mapping[str, object], text: str, timeout_s: float) -> SpeechStream:
        output_format = str(params.get("output_format", _DEFAULT_FORMAT))
        request = self._client.build_request(
            "POST", f"/v1/text-to-speech/{quote(str(params['voice_id']), safe='')}/stream",
            params={"output_format": output_format},
            json={"text": text, "model_id": model}, timeout=timeout_s)
        try:
            response = await self._client.send(request, stream=True)
        except httpx2.HTTPError as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e
        if response.is_error:
            await response.aclose()
            raise ProviderFailed(status_failure(response.status_code), f"HTTP status={response.status_code}")
        body = response.aiter_bytes()
        try:
            first = await anext(body)
        except StopAsyncIteration:
            await response.aclose()
            raise ProviderFailed("invalid_output", "the response held no audio") from None
        except httpx2.HTTPError as e:
            await response.aclose()
            raise ProviderFailed("unavailable", type(e).__name__) from e
        pcm = _FORMAT.fullmatch(output_format)
        if pcm is not None and pcm.group(1) is not None:
            return SpeechStream("audio/wav", _rest(wav_header(int(pcm.group(1))) + first, body), response.aclose)
        return SpeechStream("audio/mpeg", _rest(first, body), response.aclose)


def wav_header(rate: int) -> bytes:
    """The 44-byte RIFF/WAVE header for 16-bit little-endian mono PCM at `rate`, sizes unknown (0xFFFFFFFF)."""
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
                       b"data", 0xFFFFFFFF)


async def _rest(first: bytes, body: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    yield first
    try:
        async for chunk in body:
            yield chunk
    except httpx2.HTTPError as e:
        raise ProviderFailed("unavailable", type(e).__name__) from e
