"""`WyomingTranscriber` against an in-process Wyoming server: what goes on the wire, when, and how it fails."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from ashley.inference.provider import ProviderFailed
from ashley.inference.wyoming_stt import WyomingTranscriber
from speech_support import FORMAT, PCM, WyomingServer, heard, pcm, run
from wyoming.asr import Transcribe
from wyoming.audio import AudioChunk, AudioStart, AudioStop


def test_the_utterance_goes_over_in_order_and_the_transcript_comes_back() -> None:
    async def scenario() -> None:
        async with WyomingServer("hello there") as server:
            text = await WyomingTranscriber("wyoming", server.uri).transcribe(
                "whisper", {"language": "en"}, FORMAT, heard().chunks, 5.0)
            assert text == "hello there"
            kinds = [e.type for e in server.events]
            assert kinds == ["transcribe", "audio-start", "audio-chunk", "audio-chunk",
                             "audio-chunk", "audio-stop"]
            assert Transcribe.from_event(server.sent(Transcribe)[0]).name == "whisper"
            assert Transcribe.from_event(server.sent(Transcribe)[0]).language == "en"
            start = AudioStart.from_event(server.sent(AudioStart)[0])
            assert (start.rate, start.width, start.channels) == (16000, 2, 1)
            assert [AudioChunk.from_event(e).audio for e in server.sent(AudioChunk)] == PCM

    run(scenario())


def test_chunks_reach_the_server_while_the_person_is_still_talking() -> None:
    async def scenario() -> None:
        async with WyomingServer() as server:
            gate = asyncio.Event()
            call = asyncio.create_task(WyomingTranscriber("wyoming", server.uri).transcribe(
                "whisper", {}, FORMAT, pcm(PCM, gate), 5.0))
            await asyncio.wait_for(server.first_chunk.wait(), 3.0)
            assert not call.done() and not server.sent(AudioStop)
            gate.set()
            assert await call == "hello there"

    run(scenario())


def test_waiting_for_the_speaker_is_not_what_the_timeout_bounds() -> None:
    async def slow() -> AsyncIterator[bytes]:
        yield PCM[0]
        await asyncio.sleep(0.4)
        yield PCM[1]

    async def scenario() -> None:
        async with WyomingServer() as server:
            assert await WyomingTranscriber("wyoming", server.uri).transcribe("w", {}, FORMAT, slow(), 0.2) == \
                "hello there"

    run(scenario())


def test_a_server_that_never_answers_fails_unavailable_after_the_timeout() -> None:
    async def scenario() -> None:
        async with WyomingServer(silent=True) as server:
            with pytest.raises(ProviderFailed) as caught:
                await WyomingTranscriber("wyoming", server.uri).transcribe("w", {}, FORMAT, heard().chunks, 0.2)
            assert caught.value.failure == "unavailable"

    run(scenario())


def test_a_server_that_hangs_up_without_a_transcript_fails_unavailable() -> None:
    async def scenario() -> None:
        async with WyomingServer(reply=None) as server:
            with pytest.raises(ProviderFailed) as caught:
                await WyomingTranscriber("wyoming", server.uri).transcribe("w", {}, FORMAT, heard().chunks, 2.0)
            assert caught.value.failure == "unavailable"

    run(scenario())


def test_nothing_listening_fails_unavailable() -> None:
    async def scenario() -> None:
        async with WyomingServer() as server:
            uri = server.uri
        with pytest.raises(ProviderFailed) as caught:
            await WyomingTranscriber("wyoming", uri).transcribe("w", {}, FORMAT, heard().chunks, 2.0)
        assert caught.value.failure == "unavailable"

    run(scenario())


def test_a_source_that_breaks_fails_the_call_as_an_error() -> None:
    async def broken() -> AsyncIterator[bytes]:
        yield PCM[0]
        raise RuntimeError("microphone gone")

    async def scenario() -> None:
        async with WyomingServer() as server:
            with pytest.raises(ProviderFailed) as caught:
                await WyomingTranscriber("wyoming", server.uri).transcribe("w", {}, FORMAT, broken(), 2.0)
            assert caught.value.failure == "error"

    run(scenario())


def test_an_address_that_is_not_wyoming_is_refused_when_wired() -> None:
    with pytest.raises(ValueError):
        WyomingTranscriber("wyoming", "http://stt:10300")


@pytest.mark.parametrize("params, ok", [({}, True), ({"language": "en"}, True), ({"language": " "}, False),
                                        ({"language": 3}, False), ({"beam": 1}, False)])
def test_params_are_language_only(params: dict[str, object], ok: bool) -> None:
    provider = WyomingTranscriber("wyoming", "tcp://127.0.0.1:1")
    if ok:
        provider.check_transcribe_params(params)
    else:
        with pytest.raises(ValueError):
            provider.check_transcribe_params(params)
