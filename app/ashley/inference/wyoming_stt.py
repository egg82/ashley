"""`WyomingTranscriber`: speech to text over the Wyoming protocol (faster-whisper's server). Each call opens a
connection, sends `Transcribe`, `AudioStart`, one `AudioChunk` per chunk as it arrives and `AudioStop`, and reads the
`Transcript`, so the server decodes while the person is still talking.

Route `model` is the Wyoming model name sent in `Transcribe`. Params: `language` (non-empty string, optional; a language given per call replaces it).
`timeout_s` bounds connecting, each write and the wait for the transcript after `AudioStop`. A refused or dropped
connection, a timeout, or a server that closes without a transcript fails `unavailable`; anything else `error`."""

import asyncio
from collections.abc import AsyncIterator, Mapping

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient

from .provider import ProviderFailed
from .speech import AudioFormat
from .speech_provider import Transcriber


class WyomingTranscriber(Transcriber):
    def __init__(self, name: str, uri: str) -> None:
        """`uri` is `tcp://host:port` (or `unix://path`); anything else raises ValueError."""
        AsyncClient.from_uri(uri)
        self._name = name
        self._uri = uri

    @property
    def name(self) -> str:
        return self._name

    @property
    def uri(self) -> str:
        return self._uri

    def check_transcribe_params(self, params: Mapping[str, object]) -> None:
        unknown = sorted(set(params) - {"language"})
        if unknown:
            raise ValueError(f"unknown parameter {unknown[0]!r}")
        language = params.get("language", "x")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language must be a non-empty string")

    async def transcribe(self, model: str, params: Mapping[str, object], format: AudioFormat,
                         chunks: AsyncIterator[bytes], timeout_s: float, language: str | None = None) -> str:
        chosen = language or params.get("language")
        client = AsyncClient.from_uri(self._uri, connect_timeout=timeout_s, read_timeout=timeout_s)
        try:
            async with client:
                await _send(client, Transcribe(name=model, language=chosen if isinstance(chosen, str) else None),
                            timeout_s)
                await _send(client, AudioStart(format.rate, format.width, format.channels), timeout_s)
                async for chunk in chunks:
                    await _send(client, AudioChunk(format.rate, format.width, format.channels, chunk), timeout_s)
                await _send(client, AudioStop(), timeout_s)
                return await _transcript(client)
        except ProviderFailed:
            raise
        except (OSError, TimeoutError, EOFError) as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e


async def _send(client: AsyncClient, event: Transcribe | AudioStart | AudioChunk | AudioStop,
                timeout_s: float) -> None:
    async with asyncio.timeout(timeout_s):
        await client.write_event(event.event())


async def _transcript(client: AsyncClient) -> str:
    while (event := await client.read_event()) is not None:
        if Transcript.is_type(event.type):
            return Transcript.from_event(event).text
    raise ProviderFailed("unavailable", "connection closed before a transcript")
