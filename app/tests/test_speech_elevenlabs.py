"""`ElevenLabsSpeaker` against an in-process server: the request it sends, that speech starts before the body ends, and
how each failure is classified."""

import asyncio
import io
import json
import struct
import wave
from collections.abc import AsyncIterator

import httpx2
import pytest
from ashley.inference.elevenlabs_tts import ElevenLabsSpeaker, wav_header
from ashley.inference.provider import ProviderFailed
from speech_support import run

VOICE = "DlbsiZVVCoinytYA5J3d"
PARAMS: dict[str, object] = {"voice_id": VOICE, "output_format": "mp3_44100_64"}


def speaker(handler: httpx2.MockTransport) -> tuple[ElevenLabsSpeaker, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler.handle_request(request)

    client = httpx2.AsyncClient(base_url="https://api.test", headers={"xi-api-key": "k"},
                                transport=httpx2.MockTransport(record))
    return ElevenLabsSpeaker("elevenlabs", client), seen


def body_of(*parts: bytes, then: Exception | None = None, hold: asyncio.Event | None = None) -> httpx2.MockTransport:
    async def content() -> AsyncIterator[bytes]:
        yield parts[0]
        if hold is not None:
            await hold.wait()
        for part in parts[1:]:
            yield part
        if then is not None:
            raise then

    return httpx2.MockTransport(lambda r: httpx2.Response(200, content=content()))


async def drain(chunks: AsyncIterator[bytes]) -> list[bytes]:
    return [c async for c in chunks]


def test_the_request_names_the_voice_the_model_the_format_and_the_text() -> None:
    s, seen = speaker(body_of(b"abc"))
    stream = run(s.speak("eleven_flash_v2_5", PARAMS, "Hi there.", 5.0))
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", f"/v1/text-to-speech/{VOICE}/stream")
    assert request.url.params["output_format"] == "mp3_44100_64"
    assert request.headers["xi-api-key"] == "k"
    assert json.loads(request.content) == {"text": "Hi there.", "model_id": "eleven_flash_v2_5"}
    assert stream.media_type == "audio/mpeg"


def test_speech_starts_before_the_provider_has_finished() -> None:
    async def scenario() -> None:
        hold = asyncio.Event()
        s, _ = speaker(body_of(b"first", b"second", hold=hold))
        stream = await s.speak("m", PARAMS, "hi", 5.0)
        assert await anext(stream.chunks) == b"first"
        hold.set()
        assert await drain(stream.chunks) == [b"second"]
        await stream.close()

    run(scenario())


def test_warm_sends_a_head_to_the_root_of_the_client() -> None:
    s, seen = speaker(httpx2.MockTransport(lambda r: httpx2.Response(200)))
    assert run(s.warm(5.0)) is None
    assert [(r.method, r.url.path) for r in seen] == [("HEAD", "/")]
    assert seen[0].headers["xi-api-key"] == "k"


@pytest.mark.parametrize("status", [200, 401, 404, 405, 429, 503])
def test_warm_takes_any_http_status_as_a_warm_connection(status: int) -> None:
    s, seen = speaker(httpx2.MockTransport(lambda r: httpx2.Response(status)))
    assert run(s.warm(5.0)) is None
    assert len(seen) == 1


@pytest.mark.parametrize("error", [httpx2.ConnectError("down"), httpx2.ConnectTimeout("slow"),
                                   httpx2.ReadTimeout("slow")])
def test_warm_that_cannot_connect_or_times_out_fails_unavailable(error: Exception) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise error

    s, _ = speaker(httpx2.MockTransport(refuse))
    with pytest.raises(ProviderFailed) as caught:
        run(s.warm(5.0))
    assert caught.value.failure == "unavailable"


def test_a_voice_id_cannot_escape_its_path_segment() -> None:
    s, seen = speaker(body_of(b"x"))
    run(s.speak("m", {"voice_id": "a/b?c"}, "hi", 5.0))
    assert seen[0].url.raw_path.split(b"?")[0] == b"/v1/text-to-speech/a%2Fb%3Fc/stream"


@pytest.mark.parametrize("status, failure", [(401, "unavailable"), (402, "unavailable"), (429, "unavailable"),
                                             (503, "unavailable"), (400, "error"), (422, "error")])
def test_an_error_status_is_classified(status: int, failure: str) -> None:
    s, _ = speaker(httpx2.MockTransport(lambda r: httpx2.Response(status, json={"detail": "x"})))
    with pytest.raises(ProviderFailed) as caught:
        run(s.speak("m", PARAMS, "hi", 5.0))
    assert caught.value.failure == failure


def test_a_response_with_no_audio_is_invalid_output() -> None:
    s, _ = speaker(httpx2.MockTransport(lambda r: httpx2.Response(200, content=b"")))
    with pytest.raises(ProviderFailed) as caught:
        run(s.speak("m", PARAMS, "hi", 5.0))
    assert caught.value.failure == "invalid_output"


def test_a_connection_that_cannot_be_made_fails_unavailable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    s, _ = speaker(httpx2.MockTransport(refuse))
    with pytest.raises(ProviderFailed) as caught:
        run(s.speak("m", PARAMS, "hi", 5.0))
    assert caught.value.failure == "unavailable"


def test_a_break_after_audio_started_surfaces_from_the_chunks() -> None:
    async def scenario() -> None:
        s, _ = speaker(body_of(b"one", b"two", then=httpx2.ReadError("cut")))
        stream = await s.speak("m", PARAMS, "hi", 5.0)
        got = [await anext(stream.chunks), await anext(stream.chunks)]
        assert got == [b"one", b"two"]
        with pytest.raises(ProviderFailed) as caught:
            await anext(stream.chunks)
        assert caught.value.failure == "unavailable"
        await stream.close()

    run(scenario())


@pytest.mark.parametrize("params, ok", [
    (PARAMS, True), ({"voice_id": VOICE}, True), ({}, False), ({"voice_id": " "}, False),
    ({"voice_id": VOICE, "output_format": "pcm_16000"}, True), ({"voice_id": VOICE, "output_format": "pcm_"}, False),
    ({"voice_id": VOICE, "output_format": "pcm_x"}, False), ({"voice_id": VOICE, "output_format": "ulaw_8000"}, False),
    ({"voice_id": VOICE, "output_format": "mp3_x"}, False),
    ({"voice_id": VOICE, "stability": 1}, False)])
def test_speak_params(params: dict[str, object], ok: bool) -> None:
    s, _ = speaker(body_of(b"x"))
    if ok:
        s.check_speak_params(params)
    else:
        with pytest.raises(ValueError):
            s.check_speak_params(params)


def test_the_wav_header_is_16_bit_mono_at_the_rate_with_sizes_left_unknown() -> None:
    header = wav_header(16000)
    assert len(header) == 44
    assert struct.unpack("<4sI4s", header[:12]) == (b"RIFF", 0xFFFFFFFF, b"WAVE")
    assert struct.unpack("<4sI", header[36:]) == (b"data", 0xFFFFFFFF)
    assert struct.unpack("<4sIHHIIHH", header[12:36]) == (b"fmt ", 16, 1, 1, 16000, 32000, 2, 16)
    pcm = struct.pack("<4h", 1, -2, 3, -4)
    with wave.open(io.BytesIO(header + pcm)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.readframes(10) == pcm
    with wave.open(io.BytesIO(wav_header(22050))) as w:
        assert w.getframerate() == 22050


def test_pcm_speech_is_a_wav_stream_whose_header_waits_for_the_first_audio_and_nothing_is_buffered() -> None:
    async def scenario() -> None:
        hold = asyncio.Event()
        s, seen = speaker(body_of(b"\x01\x00", b"\x02\x00", hold=hold))
        stream = await s.speak("m", {"voice_id": VOICE, "output_format": "pcm_16000"}, "hi", 5.0)
        assert seen[0].url.params["output_format"] == "pcm_16000"
        assert stream.media_type == "audio/wav"
        assert await anext(stream.chunks) == wav_header(16000) + b"\x01\x00"
        hold.set()
        assert await drain(stream.chunks) == [b"\x02\x00"]
        await stream.close()

    run(scenario())


def test_pcm_with_no_audio_is_invalid_output_even_though_the_header_exists() -> None:
    s, _ = speaker(httpx2.MockTransport(lambda r: httpx2.Response(200, content=b"")))
    with pytest.raises(ProviderFailed) as caught:
        run(s.speak("m", {"voice_id": VOICE, "output_format": "pcm_16000"}, "hi", 5.0))
    assert caught.value.failure == "invalid_output"
