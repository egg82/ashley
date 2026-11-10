"""A video file is a `clip` piece and an audio file an `audio` piece, chosen by the bytes' signature; a large piece's body
is fixed; the file link answers one `Range` (206, else 200; 416 past the end); a cue drives a clip or an audio piece."""

import time
from typing import Any

import pytest
from ashley.files import links
from ashley.live.events import BenchCued
from ashley.workshop.commands import Add, Cue, Edit
from ashley.workshop.embed import MAX_START
from ashley.workshop.model import HER, By, Text
from ashley.workshop.stored_file import StoredFile, body_of
from bench_media_blind_support import (FILES, FLAC, LINK_KEY, M4A, MP3, MP4, OGG, PDF, PNG, QUICKTIME, WAV, WEBM, WEBP,
                                       ftyp, go, rig, scene, sha)

CASES: list[tuple[str, bytes, str, str]] = [
    ("isom.mp4", MP4, "video/mp4", "clip"),
    ("iso2.mp4", ftyp(b"iso2"), "video/mp4", "clip"),
    ("mp41.mp4", ftyp(b"mp41"), "video/mp4", "clip"),
    ("mp42.mp4", ftyp(b"mp42"), "video/mp4", "clip"),
    ("avc1.mp4", ftyp(b"avc1"), "video/mp4", "clip"),
    ("m4v.m4v", ftyp(b"M4V "), "video/mp4", "clip"),
    ("movie.mov", QUICKTIME, "video/quicktime", "clip"),
    ("movie.webm", WEBM, "video/webm", "clip"),
    ("song.m4a", M4A, "audio/mp4", "audio"),
    ("book.m4b", ftyp(b"M4B "), "audio/mp4", "audio"),
    ("tagged.mp3", MP3, "audio/mpeg", "audio"),
    ("raw.mp3", bytes.fromhex("fffb9000") + b"frame", "audio/mpeg", "audio"),
    ("raw2.mp3", bytes.fromhex("fff3") + b"frame", "audio/mpeg", "audio"),
    ("raw3.mp3", bytes.fromhex("fff2") + b"frame", "audio/mpeg", "audio"),
    ("voice.ogg", OGG, "audio/ogg", "audio"),
    ("voice.wav", WAV, "audio/wav", "audio"),
    ("voice.flac", FLAC, "audio/flac", "audio"),
]


@pytest.mark.parametrize(("name", "data", "media", "kind"), CASES, ids=[c[0] for c in CASES])
def test_the_bytes_choose_the_kind_of_piece(db_url: str, name: str, data: bytes, media: str, kind: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, data, name)
        assert got.status_code == 200
        (piece,) = r.pieces(b)
        assert piece["id"] == got.json()["piece_id"] and piece["kind"] == kind and piece["title"] == name
        assert piece["file"]["media_type"] == media and piece["file"]["size_bytes"] == len(data)
        assert r.store.held and list(r.store.held.values()) == [data]


def test_a_kind_follows_the_bytes_not_the_name(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, MP3, "really-a-video.mp4")
        r.upload(b, MP4, "really-audio.mp3")
        assert [p["kind"] for p in r.pieces(b)] == ["audio", "clip"]


def test_a_wav_and_a_webp_share_a_header_and_are_told_apart(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, WAV, "a.bin")
        r.upload(b, WEBP, "b.bin")
        assert [p["kind"] for p in r.pieces(b)] == ["audio", "image"]


def test_images_and_documents_are_still_not_players(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "p.png")
        r.upload(b, PDF, "d.pdf")
        assert [p["kind"] for p in r.pieces(b)] == ["image", "file"]


@pytest.mark.parametrize(("data", "declared"), [(MP4, "video/webm"), (MP4, "audio/mpeg"), (MP3, "video/mp4"), (WEBM, "audio/ogg")])
def test_a_declared_type_that_is_another_one_is_refused_and_nothing_is_added(db_url: str, data: bytes, declared: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, data, "x.bin", declared)
        assert got.status_code == 415
        assert r.pieces(b) == [] and r.store.held == {}


def test_a_declared_type_that_is_right_is_taken(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        assert r.upload(b, MP4, "x.bin", "video/mp4").status_code == 200
        assert r.pieces(b)[0]["kind"] == "clip"


def test_a_container_of_an_unlisted_brand_is_not_a_recording(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, ftyp(b"heic"), "photo.heic")
        assert got.status_code == 415 and r.pieces(b) == []


def test_the_shipped_types_name_the_pieces_players_show() -> None:
    assert [FILES.piece_kind(m) for m in ("video/mp4", "video/quicktime", "video/webm")] == ["clip"] * 3
    assert [FILES.piece_kind(m) for m in ("audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/flac")] == ["audio"] * 5
    assert [FILES.piece_kind(m) for m in ("image/png", "application/pdf", "text/plain")] == ["image", "file", "file"]
    assert all(FILES.plays(m) for m in ("video/mp4", "audio/ogg")) and not any(FILES.plays(m) for m in ("image/png", "text/plain"))


def link_of(r: Any, bench: int) -> str:
    url: str = r.pieces(bench)[0]["file"]["url"]
    return url


@pytest.fixture
def clip(db_url: str) -> Any:
    with rig(db_url) as r:
        b = r.new_bench()
        data = MP4 + bytes(range(100))
        assert r.upload(b, data, "v.mp4").status_code == 200
        r.data, r.url = data, link_of(r, b)
        yield r


def test_without_a_range_the_whole_file_is_200(clip: Any) -> None:
    got = clip.client.get(clip.url)
    assert got.status_code == 200 and got.content == clip.data


def test_a_range_is_206_with_exactly_those_bytes(clip: Any) -> None:
    got = clip.client.get(clip.url, headers={"range": "bytes=10-19"})
    n = len(clip.data)
    assert got.status_code == 206 and got.content == clip.data[10:20]
    assert got.headers["content-range"] == f"bytes 10-19/{n}" and got.headers["content-length"] == "10"


def test_an_open_ended_range_runs_to_the_end(clip: Any) -> None:
    got = clip.client.get(clip.url, headers={"range": "bytes=40-"})
    n = len(clip.data)
    assert got.status_code == 206 and got.content == clip.data[40:] and got.headers["content-range"] == f"bytes 40-{n - 1}/{n}"


def test_a_suffix_range_is_the_last_bytes(clip: Any) -> None:
    got = clip.client.get(clip.url, headers={"range": "bytes=-7"})
    assert got.status_code == 206 and got.content == clip.data[-7:]


def test_a_range_ending_past_the_end_is_cut_at_the_end(clip: Any) -> None:
    n = len(clip.data)
    got = clip.client.get(clip.url, headers={"range": f"bytes={n - 5}-{n + 500}"})
    assert got.status_code == 206 and got.content == clip.data[-5:] and got.headers["content-range"] == f"bytes {n - 5}-{n - 1}/{n}"


def test_the_first_byte_alone_is_a_range(clip: Any) -> None:
    got = clip.client.get(clip.url, headers={"range": "bytes=0-0"})
    assert got.status_code == 206 and got.content == clip.data[:1]


@pytest.mark.parametrize("start", [0, 1, 50])
def test_a_range_starting_past_the_end_is_416_refused(clip: Any, start: int) -> None:
    n = len(clip.data)
    got = clip.client.get(clip.url, headers={"range": f"bytes={n + start}-"})
    assert got.status_code == 416 and got.json()["code"] == "refused"


def test_the_last_byte_is_still_in_range(clip: Any) -> None:
    n = len(clip.data)
    got = clip.client.get(clip.url, headers={"range": f"bytes={n - 1}-"})
    assert got.status_code == 206 and got.content == clip.data[-1:]


def test_a_range_is_served_with_the_files_type_and_nosniff(clip: Any) -> None:
    whole, part = clip.client.get(clip.url), clip.client.get(clip.url, headers={"range": "bytes=0-9"})
    assert part.headers["content-type"] == whole.headers["content-type"] == "video/mp4"
    assert part.headers.get("x-content-type-options") == "nosniff"


def test_a_range_header_that_is_not_one_serves_the_whole_file(clip: Any) -> None:
    got = clip.client.get(clip.url, headers={"range": "pages=1-2"})
    assert got.status_code == 200 and got.content == clip.data


def test_a_range_needs_the_link_as_much_as_a_whole_read(clip: Any) -> None:
    token = clip.url.rsplit("/", 1)[1]
    bad = clip.url.replace(token, token[:-2] + ("aa" if not token.endswith("aa") else "bb"))
    assert clip.client.get(bad, headers={"range": "bytes=0-9"}).status_code == 404


def test_an_expired_link_serves_no_range(clip: Any) -> None:
    grant = links.Grant(clip.owner.household_id, sha(clip.data), "video/mp4", False, int(time.time()) - 5)
    url = links.mint(LINK_KEY.encode(), grant).url
    assert clip.client.get(url, headers={"range": "bytes=0-9"}).status_code == 404


def test_an_audio_file_is_ranged_the_same_way(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        data = MP3 + bytes(200)
        r.upload(b, data, "a.mp3")
        got = r.client.get(link_of(r, b), headers={"range": "bytes=3-12"})
        assert got.status_code == 206 and got.content == data[3:13] and got.headers["content-type"] == "audio/mpeg"


def stored(data: bytes, media: str, name: str = "x") -> str:
    return body_of(StoredFile(sha(data), len(data), media, name))


@pytest.mark.parametrize("kind", ["clip", "audio"])
def test_a_recording_cannot_be_added_with_a_body_that_is_not_a_stored_file(db_url: str, kind: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            for text in ("", "{}", "https://example.com/v.mp4", "not json"):
                got = await s.workshop.apply(s.alana, s.bench, Add(HER, kind, Text("t", text), "medium"))
                assert got.outcome != "accepted", text
            assert await s.pieces() == ()

    go(scenario())


@pytest.mark.parametrize(("kind", "media", "ok"), [("clip", "video/mp4", True), ("clip", "audio/mpeg", False), ("clip", "image/png", False),
                                                    ("audio", "audio/mpeg", True), ("audio", "video/mp4", False), ("audio", "application/pdf", False)])
def test_a_kind_takes_only_a_stored_file_of_its_sort(db_url: str, kind: str, media: str, ok: bool) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            got = await s.workshop.apply(s.alana, s.bench, Add(HER, kind, Text("t", stored(b"abc", media)), "medium"))
            assert (got.outcome == "accepted") is ok

    go(scenario())


def test_a_recordings_bytes_are_fixed_but_its_title_is_not(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            piece = await s.put(MP4, "v.mp4")
            other = stored(b"zzz", "video/mp4")
            changed = await s.workshop.apply(s.alana, s.bench, Edit(HER, piece.id, piece.version, Text(piece.text.title, other)))
            assert changed.outcome != "accepted"
            retitled = await s.workshop.apply(s.alana, s.bench, Edit(HER, piece.id, piece.version, Text("new title", piece.text.body)))
            assert retitled.outcome == "accepted"
            (now,) = await s.pieces()
            assert now.text.title == "new title" and now.text.body == piece.text.body

    go(scenario())


def cue(piece_id: int, action: Any, seconds: float | None = None, by: By = HER) -> Cue:
    return Cue(by, piece_id, action, seconds)


@pytest.mark.parametrize(("name", "data"), [("v.mp4", MP4), ("a.mp3", MP3)])
def test_a_cue_drives_a_clip_and_an_audio_piece(db_url: str, name: str, data: bytes) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            piece = await s.put(data, name)
            for command in (cue(piece.id, "play"), cue(piece.id, "pause"), cue(piece.id, "seek", 12.5), cue(piece.id, "seek", 0),
                            cue(piece.id, "seek", MAX_START)):
                assert (await s.workshop.apply(s.alana, s.bench, command)).outcome == "accepted", command
            cues = [e for e in s.live.published if isinstance(e, BenchCued)]
            assert [(e.piece_id, e.action, e.seconds) for e in cues][:3] == [(piece.id, "play", None), (piece.id, "pause", None), (piece.id, "seek", 12.5)]
            (after,) = await s.pieces()
            assert after.version == piece.version and after.text == piece.text

    go(scenario())


@pytest.mark.parametrize("command", [("seek", None), ("seek", -1), ("seek", MAX_START + 1), ("play", 3.0), ("pause", 3.0)])
def test_a_bad_cue_of_a_recording_is_refused_and_tells_nobody(db_url: str, command: tuple[str, float | None]) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            piece = await s.put(MP4, "v.mp4")
            before = len(s.live.published)
            got = await s.workshop.apply(s.alana, s.bench, cue(piece.id, command[0], command[1]))
            assert got.outcome != "accepted"
            assert not [e for e in s.live.published[before:] if isinstance(e, BenchCued)]

    go(scenario())


@pytest.mark.parametrize(("name", "data"), [("p.png", PNG), ("d.pdf", PDF)])
def test_a_cue_of_a_picture_or_a_document_is_still_refused(db_url: str, name: str, data: bytes) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            piece = await s.put(data, name)
            assert (await s.workshop.apply(s.alana, s.bench, cue(piece.id, "play"))).outcome != "accepted"

    go(scenario())
