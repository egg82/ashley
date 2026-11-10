"""`BenchPiece.video` through the real routes and database, the refusals as 409, and her hints for both reasons."""

from collections.abc import Generator
from typing import Any

import pytest
from ashley.api.workshop_models import BenchDetail, BenchPiece, BenchSummary, CommandRefused
from ashley.tools.bench_results import HINTS
from ashley.workshop.commands import REASONS, Reason
from respond_support import Fakes, wired as wired
from sv_support import Rig, build

YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VIDEO = '{"url": "%s", "start": 42}' % YT


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def bench(rig: Rig) -> int:
    return int(BenchSummary.model_validate(rig.post("/api/benches", {"title": "b"}).json).id)


def send(rig: Rig, bench_id: int, body: dict[str, object]) -> tuple[int, dict[str, Any]]:
    got = rig.post(f"/api/benches/{bench_id}/commands", body)
    return got.status, got.json


def add(rig: Rig, bench_id: int, kind: str, text: str) -> tuple[int, dict[str, Any]]:
    return send(rig, bench_id, {"type": "add", "kind": kind, "title": "t", "body": text, "size": "small"})


def detail(rig: Rig, bench_id: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench_id}")
    assert got.status == 200
    return BenchDetail.model_validate(got.json)


def by_kind(pieces: list[BenchPiece]) -> dict[str, BenchPiece]:
    return {p.kind: p for p in pieces}


def test_a_video_piece_carries_its_video_and_every_other_piece_null(rig: Rig) -> None:
    b = bench(rig)
    for kind, text in (("video", VIDEO), ("site", "https://example.com/x"), ("note", YT), ("document", VIDEO)):
        assert add(rig, b, kind, text)[0] == 200
    pieces = by_kind(detail(rig, b).pieces)
    v = pieces["video"].video
    assert v is not None and (v.provider, v.url, v.start) == ("youtube", YT, 42)
    assert v.embed_url.startswith("https://") and "youtube-nocookie.com/embed/dQw4w9WgXcQ" in v.embed_url
    assert "start=42" in v.embed_url and "autoplay" not in v.embed_url
    assert pieces["site"].video is None and pieces["note"].video is None and pieces["document"].video is None


def test_a_video_piece_with_no_body_yet_has_null_video(rig: Rig) -> None:
    b = bench(rig)
    assert add(rig, b, "video", "")[0] == 200
    assert by_kind(detail(rig, b).pieces)["video"].video is None


def test_the_wire_names_exactly_provider_url_embed_url_start(rig: Rig) -> None:
    b = bench(rig)
    add(rig, b, "video", '{"url": "https://cdn.example.com/a.mp4", "start": 5}')
    raw = rig.get(f"/api/benches/{b}").json["pieces"][0]
    assert raw["video"] == {"provider": "file", "url": "https://cdn.example.com/a.mp4",
                            "embed_url": "https://cdn.example.com/a.mp4", "start": 5}
    assert "video" in raw


def test_an_edit_changes_the_video_and_an_edit_to_empty_clears_it(rig: Rig) -> None:
    b = bench(rig)
    add(rig, b, "video", VIDEO)
    other = '{"url": "https://vimeo.com/76979871", "start": 3}'
    assert send(rig, b, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "t", "body": other})[0] == 200
    v = detail(rig, b).pieces[0].video
    assert v is not None and v.provider == "vimeo" and v.embed_url.startswith("https://player.vimeo.com/video/76979871")
    assert send(rig, b, {"type": "edit", "piece_id": 1, "base_version": 2, "title": "t", "body": ""})[0] == 200
    assert detail(rig, b).pieces[0].video is None


def test_an_archived_video_piece_keeps_its_video_on_the_shelf(rig: Rig) -> None:
    b = bench(rig)
    add(rig, b, "video", VIDEO)
    assert send(rig, b, {"type": "archive", "piece_id": 1})[0] == 200
    d = detail(rig, b)
    assert d.pieces == [] and d.shelf[0].video is not None and d.shelf[0].video.start == 42


@pytest.mark.parametrize(("kind", "text", "why"), [("site", "http://example.com", "bad_site"), ("site", "javascript:alert(1)", "bad_site"),
                                                   ("video", "junk", "bad_video"), ("video", YT, "bad_video")])
def test_a_bad_body_is_409_with_its_reason_and_adds_nothing(rig: Rig, kind: str, text: str, why: str) -> None:
    b = bench(rig)
    status, raw = add(rig, b, kind, text)
    refused = CommandRefused.model_validate(raw)
    assert status == 409 and (refused.reason, refused.seq) == (why, 1)
    d = detail(rig, b)
    assert d.pieces == [] and [c.outcome for c in d.recent] == [why]


def test_a_bad_edit_is_409_and_the_piece_is_unchanged(rig: Rig) -> None:
    b = bench(rig)
    add(rig, b, "site", "https://example.com/a")
    status, raw = send(rig, b, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "t", "body": "http://example.com"})
    assert status == 409 and CommandRefused.model_validate(raw).reason == "bad_site"
    p = detail(rig, b).pieces[0]
    assert (p.body, p.piece_version) == ("https://example.com/a", 1)


def test_her_hints_cover_both_reasons() -> None:
    reasons: tuple[Reason, Reason] = ("bad_site", "bad_video")
    for why in reasons:
        assert why in REASONS and len(HINTS[why]) > 10
    assert "https" in HINTS["bad_site"] and "url" in HINTS["bad_video"].lower()