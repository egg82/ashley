"""Transcription through an OpenAI-compatible API (`audio.transcriptions.create`): the whole utterance goes up as one
WAV file once the chunks end, so this route cannot decode while the person is talking. Used by
`OpenAICompatibleProvider` for `transcribe` routes.

Route `model` is the transcription model (`gpt-4o-mini-transcribe`). Params: `language` (non-empty string, optional; a language given per call replaces it).
Failures are classified as for chat (`providers`): a timeout, connection failure, 408, 409, 429, 5xx, 401, 402 or 403
is `unavailable`, any other status `error`."""

import io
import wave
from collections.abc import AsyncIterator, Mapping

import openai
from openai import AsyncOpenAI, omit
from openai.types.audio import Transcription

from .provider import ProviderFailed, status_failure
from .speech import AudioFormat


def check_params(params: Mapping[str, object]) -> None:
    unknown = sorted(set(params) - {"language"})
    if unknown:
        raise ValueError(f"unknown parameter {unknown[0]!r}")
    language = params.get("language", "x")
    if not isinstance(language, str) or not language.strip():
        raise ValueError("language must be a non-empty string")


async def transcribe(client: AsyncOpenAI, model: str, params: Mapping[str, object], format: AudioFormat,
                     chunks: AsyncIterator[bytes], timeout_s: float, language: str | None = None) -> str:
    audio = _wav(format, b"".join([chunk async for chunk in chunks]))
    language = language or params.get("language")
    try:
        response: object = await client.audio.transcriptions.create(
            model=model, file=("utterance.wav", audio, "audio/wav"), timeout=timeout_s,
            language=language if isinstance(language, str) else omit)
    except openai.APIStatusError as e:
        raise ProviderFailed(status_failure(e.status_code), f"{type(e).__name__} status={e.status_code}") from e
    except openai.APIConnectionError as e:
        raise ProviderFailed("unavailable", type(e).__name__) from e
    except Exception as e:
        raise ProviderFailed("error", type(e).__name__) from e
    if not isinstance(response, Transcription):
        raise ProviderFailed("error", f"unexpected response body: {type(response).__name__}")
    return response.text


def _wav(format: AudioFormat, pcm: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(format.channels)
        wav.setsampwidth(format.width)
        wav.setframerate(format.rate)
        wav.writeframes(pcm)
    return out.getvalue()
