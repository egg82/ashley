"""OpenAI-compatible transcription (`audio.transcriptions.create`) against an in-process server: the request the SDK
really sends and how each answer is classified."""

import io
import wave

import httpx
import pytest
from ashley.inference.provider import ProviderFailed
from ashley.inference.providers import OpenAICompatibleProvider
from openai import AsyncOpenAI
from speech_support import FORMAT, PCM, heard, run


def provider(handler: httpx.MockTransport) -> tuple[OpenAICompatibleProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler.handle_request(request)

    client = AsyncOpenAI(api_key="k", max_retries=0, base_url="http://stt.test/v1",
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(record)))
    return OpenAICompatibleProvider("openai", client), seen


def answer(status: int = 200, json: object = None, content: bytes | None = None) -> httpx.MockTransport:
    return httpx.MockTransport(lambda r: httpx.Response(status, json=json) if content is None
                               else httpx.Response(status, content=content))


async def transcribe(p: OpenAICompatibleProvider, params: dict[str, object] | None = None,
                     language: str | None = None) -> str:
    return await p.transcribe("gpt-4o-mini-transcribe", params or {}, FORMAT, heard().chunks, 5.0, language)


def language_sent(request: httpx.Request) -> bytes | None:
    marker = b'name="language"\r\n\r\n'
    body = request.content
    return body[body.index(marker) + len(marker):].split(b"\r\n", 1)[0] if marker in body else None


def test_the_whole_utterance_goes_up_as_one_wav_and_the_text_comes_back() -> None:
    p, seen = provider(answer(json={"text": " hello there "}))
    assert run(transcribe(p, {"language": "en"})) == " hello there "
    request = seen[0]
    assert request.url.path == "/v1/audio/transcriptions"
    body = request.content
    assert b'name="model"' in body and b"gpt-4o-mini-transcribe" in body
    assert b'name="language"' in body
    wav_start = body.index(b"RIFF")
    with wave.open(io.BytesIO(body[wav_start:body.index(b"\r\n--", wav_start)]), "rb") as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (16000, 2, 1)
        assert wav.readframes(wav.getnframes()) == b"".join(PCM)


def test_a_language_given_per_call_replaces_the_routes_and_none_leaves_it() -> None:
    p, seen = provider(answer(json={"text": "x"}))
    run(transcribe(p, {"language": "en"}, "de"))
    run(transcribe(p, {"language": "en"}))
    run(transcribe(p))
    assert [language_sent(r) for r in seen] == [b"de", b"en", None]


@pytest.mark.parametrize("status", [401, 402, 403, 408, 409, 429, 500, 503])
def test_statuses_that_say_try_elsewhere_fail_unavailable(status: int) -> None:
    p, _ = provider(answer(status, {"error": {"message": "x"}}))
    with pytest.raises(ProviderFailed) as caught:
        run(transcribe(p))
    assert caught.value.failure == "unavailable"


@pytest.mark.parametrize("status", [400, 404, 422])
def test_a_rejected_request_fails_as_an_error(status: int) -> None:
    p, _ = provider(answer(status, {"error": {"message": "x"}}))
    with pytest.raises(ProviderFailed) as caught:
        run(transcribe(p))
    assert caught.value.failure == "error"


def test_a_body_that_is_not_a_transcription_fails_as_an_error() -> None:
    p, _ = provider(answer(content=b"not json"))
    with pytest.raises(ProviderFailed) as caught:
        run(transcribe(p))
    assert caught.value.failure == "error"


def test_a_dropped_connection_fails_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    p, _ = provider(httpx.MockTransport(refuse))
    with pytest.raises(ProviderFailed) as caught:
        run(transcribe(p))
    assert caught.value.failure == "unavailable"


@pytest.mark.parametrize("params, ok", [({}, True), ({"language": "en"}, True), ({"language": ""}, False),
                                        ({"temperature": 0}, False)])
def test_transcribe_params(params: dict[str, object], ok: bool) -> None:
    p, _ = provider(answer(json={"text": ""}))
    if ok:
        p.check_transcribe_params(params)
    else:
        with pytest.raises(ValueError):
            p.check_transcribe_params(params)
