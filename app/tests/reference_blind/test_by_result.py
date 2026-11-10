"""`result` on bench_add and bench_edit of a site or video: the URL is written from the turn's `Results`, numbers are
the turn's own, a video host's page is a video and no site, a results page or channel is no video, and `result` with a
`body` is `bad_arguments`. Each case runs as an Add and as an Edit."""

import json

import pytest
from ashley.tools.results import Results
from refb_support import OTHER, WIKI, YT, body_of, error_code, rig, video_body

OPS = ["add", "edit"]
SITE_URLS = [WIKI, "https://example.com/", "https://Example.com/A/b?x=1&y=2#frag", "https://example.com/a%20b/c.html?q=%C3%A9"]
NOT_VIDEOS = [
    "https://www.youtube.com/results?search_query=cats", "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw", "https://www.youtube.com/playlist?list=PLabc123",
    "https://www.youtube.com/", "https://vimeo.com/search?q=cats"]


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("url", SITE_URLS)
def test_a_site_number_fills_the_url_exactly(op: str, url: str) -> None:
    r = rig("site")
    r.results.record(OTHER + "/first")
    n = r.results.record(url)
    got = r.put(op, "site", result=n)
    assert not got.is_error, got.content
    assert body_of(r.command()) == url
    assert r.command().text.title == "t"


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("start", [None, 0, 90])
def test_a_video_number_fills_the_url_and_carries_start(op: str, start: int | None) -> None:
    r = rig("video")
    n = r.results.record(YT)
    got = r.put(op, "video", result=n, **({} if start is None else {"start": start}))
    assert not got.is_error, got.content
    body = json.loads(body_of(r.command()))
    assert body["url"] == YT
    if start:
        assert body["start"] == start


@pytest.mark.parametrize("op", OPS)
def test_a_direct_media_file_result_is_a_video(op: str) -> None:
    r = rig("video")
    n = r.results.record("https://cdn.example.com/clip.mp4")
    assert not r.put(op, "video", result=n).is_error
    assert json.loads(body_of(r.command()))["url"] == "https://cdn.example.com/clip.mp4"


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("number", [1, 2, 7, 0, -1])
def test_a_number_nothing_was_recorded_under_is_unknown_result_and_changes_nothing(op: str, number: int) -> None:
    r = rig("site")
    r.results.record(WIKI)
    got = r.put(op, "site", result=number) if number != 1 else r.put(op, "site", result=2)
    assert error_code(got, "unknown_result"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("kind", ["site", "video"])
def test_an_empty_store_refuses_every_number_as_a_resumed_turn_does(op: str, kind: str) -> None:
    earlier = Results()
    n = earlier.record(WIKI)
    r = rig(kind, results=Results())
    got = r.put(op, kind, result=n)
    assert error_code(got, "unknown_result"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
def test_numbers_are_per_turn_one_turns_number_never_reaches_anothers_url(op: str) -> None:
    mine, theirs = Results(), Results()
    mine.record("https://example.org/mine-1")
    mine.record("https://example.org/mine-2")
    theirs.record("https://example.org/theirs-1")
    r = rig("site", results=theirs)
    assert error_code(r.put(op, "site", result=2), "unknown_result")
    assert r.shop.applied == []
    assert not r.put(op, "site", result=1).is_error
    assert body_of(r.command()) == "https://example.org/theirs-1"


@pytest.mark.parametrize("op", OPS)
def test_a_youtube_result_as_a_site_is_refused_and_as_a_video_accepted(op: str) -> None:
    r = rig("site")
    n = r.results.record(YT)
    got = r.put(op, "site", result=n)
    assert error_code(got, "bad_site"), got.content
    assert r.shop.applied == []
    v = rig("video")
    n = v.results.record(YT)
    assert not v.put(op, "video", result=n, start=42).is_error
    assert json.loads(body_of(v.command())) == {"url": YT, "start": 42}


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("url", NOT_VIDEOS)
def test_a_results_page_or_channel_as_a_video_is_refused(op: str, url: str) -> None:
    r = rig("video")
    n = r.results.record(url)
    got = r.put(op, "video", result=n)
    assert error_code(got, "bad_video"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("kind", ["site", "video"])
def test_result_together_with_a_body_is_bad_arguments(op: str, kind: str) -> None:
    r = rig(kind)
    n = r.results.record(WIKI if kind == "site" else YT)
    body = WIKI if kind == "site" else video_body(YT)
    got = r.put(op, kind, result=n, body=body)
    assert error_code(got, "bad_arguments"), got.content
    assert r.shop.applied == []


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("bad", ["1", 1.5, True, None, [1]])
def test_a_result_that_is_no_integer_changes_nothing(op: str, bad: object) -> None:
    r = rig("site")
    r.results.record(WIKI)
    got = r.put(op, "site", result=bad)
    assert got.is_error, got.content
    assert r.shop.applied == []


def test_a_number_is_a_reference_by_value_not_by_position_a_later_record_does_not_change_it() -> None:
    r = rig("site")
    n = r.results.record(WIKI)
    r.results.record("https://example.org/later")
    assert not r.put("add", "site", result=n).is_error
    assert body_of(r.command()) == WIKI


@pytest.mark.parametrize("op", OPS)
def test_start_belongs_to_a_video_with_a_result(op: str) -> None:
    site = rig("site")
    n = site.results.record(WIKI)
    assert site.put(op, "site", result=n, start=30).is_error
    assert site.shop.applied == []
    video = rig("video")
    video.results.record(YT)
    assert video.put(op, "video", start=30, body=video_body(YT)).is_error
    assert video.shop.applied == []


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("kind", ["note", "document"])
def test_a_result_on_a_piece_that_shows_no_page_is_refused(op: str, kind: str) -> None:
    r = rig(kind)
    n = r.results.record(WIKI)
    assert r.put(op, kind, result=n).is_error
    assert r.shop.applied == []
