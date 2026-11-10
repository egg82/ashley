"""Edges of the contract: arguments the tools do not define, a transcript with nothing in it, a closed bench, a tool
name that is not hers, and the `Range` forms a player sends."""

from typing import Any

import pytest
from ashley.tools.bench_media import BenchMediaTools
from bench_media_blind_support import MP3, MP4, call, go, rig, said, scene, sha


@pytest.mark.parametrize(("tool", "args"), [("bench_frames", {"at": [1], "extra": 1}), ("bench_frames", {"at": [1], "start": 3}),
                                            ("bench_transcribe", {"lang": "en"}), ("bench_transcribe", {"captions": 3})])
def test_an_argument_the_tool_does_not_define_is_an_error_and_does_nothing(db_url: str, tool: str, args: dict[str, Any]) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            before = await s.log_size()
            got = await s.tools().call(call(tool, piece_id=clip.id, **args))
            assert got.is_error and s.media.jobs() == 0 and s.looks_of() == [] and await s.log_size() == before

    go(scenario())


def test_a_tool_that_is_not_hers_is_an_error() -> None:
    async def scenario() -> None:
        got = await BenchMediaTools(1, 1, 1, 1, 1).call(call("bench_listen", piece_id=1))
        assert got.is_error

    go(scenario())


@pytest.mark.parametrize("segments", [(), ((1.0, ""), (2.0, "")), ((1.0, "  "),)])
def test_a_recording_with_nothing_said_makes_no_transcript(db_url: str, segments: tuple[tuple[float, str], ...]) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            s.media.words_to_give = said(*segments)
            before = await s.log_size()
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert got.is_error
            assert [p for p in await s.pieces() if p.kind == "reader"] == [] and await s.log_size() == before

    go(scenario())


def test_a_closed_bench_takes_no_transcript(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP3, "a.mp3")
            await s.workshop.close(s.alana, s.bench)
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert got.is_error and [p for p in await s.pieces() if p.kind == "reader"] == []

    go(scenario())


@pytest.fixture
def served(db_url: str) -> Any:
    with rig(db_url) as r:
        b = r.new_bench()
        data = MP4 + bytes(range(60))
        r.upload(b, data, "v.mp4")
        r.data, r.url = data, r.pieces(b)[0]["file"]["url"]
        yield r


def test_a_served_file_says_it_can_be_ranged(served: Any) -> None:
    got = served.client.get(served.url)
    assert got.headers["accept-ranges"] == "bytes"


def test_a_suffix_longer_than_the_file_is_the_whole_file_as_a_range(served: Any) -> None:
    n = len(served.data)
    got = served.client.get(served.url, headers={"range": f"bytes=-{n + 40}"})
    assert got.status_code == 206 and got.content == served.data and got.headers["content-range"] == f"bytes 0-{n - 1}/{n}"


@pytest.mark.parametrize("header", ["bytes=-0", "bytes=9-3"])
def test_a_range_asking_for_no_bytes_is_416(served: Any, header: str) -> None:
    got = served.client.get(served.url, headers={"range": header})
    assert got.status_code == 416


def test_a_416_says_how_long_the_file_is(served: Any) -> None:
    got = served.client.get(served.url, headers={"range": f"bytes={len(served.data)}-"})
    assert got.status_code == 416 and got.headers["content-range"] == f"bytes */{len(served.data)}"


@pytest.mark.parametrize("header", ["bytes=-", "bytes=", "bytes=a-b", "bytes=1-2,5-6", "items=1-2", ""])
def test_a_header_that_is_not_one_range_serves_the_whole_file(served: Any, header: str) -> None:
    got = served.client.get(served.url, headers={"range": header})
    assert got.status_code == 200 and got.content == served.data


def test_a_range_over_a_file_fetches_the_same_bytes_as_the_whole_in_pieces(served: Any) -> None:
    n = len(served.data)
    parts = b"".join(served.client.get(served.url, headers={"range": f"bytes={i}-{min(i + 15, n - 1)}"}).content for i in range(0, n, 16))
    assert parts == served.data and sha(parts) == sha(served.data)
