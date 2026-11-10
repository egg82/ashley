"""A site piece's body is an https URL; a video piece's body is a JSON object `{"url": ..., "start": seconds}` whose
URL is a YouTube or Vimeo page or a direct media file, shown through the provider's privacy embed. An empty body of
either is a draft."""

import json

import pytest
from ashley.workshop import embed


def vid(url: object, **rest: object) -> str:
    return json.dumps({"url": url, **rest})


@pytest.mark.parametrize("text", ["", "  ", "https://en.wikipedia.org/wiki/Graph_theory", "https://a.example/p?q=1#x"])
def test_a_site_body_is_empty_or_an_https_url(text: str) -> None:
    assert embed.site_well_formed(text)


@pytest.mark.parametrize("text", [
    "http://a.example/", "javascript:alert(1)", "data:text/html,hi", "//a.example/", "a.example", "https://",
    "https://user:pw@a.example/", "https://a.example/ x", "https://a.example/\nx", "see https://a.example/",
    "ftp://a.example/", "https://" + "a" * 2100 + ".example/"])
def test_a_site_body_that_is_not_an_https_url_is_refused(text: str) -> None:
    assert not embed.site_well_formed(text)


@pytest.mark.parametrize("url, embed_url", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://m.youtube.com/shorts/dQw4w9WgXcQ", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://vimeo.com/76979871", "https://player.vimeo.com/video/76979871"),
    ("https://player.vimeo.com/video/76979871", "https://player.vimeo.com/video/76979871"),
    ("https://vimeo.com/76979871/a1b2c3d4e5", "https://player.vimeo.com/video/76979871?h=a1b2c3d4e5"),
    ("https://player.vimeo.com/video/76979871?h=a1b2c3d4e5", "https://player.vimeo.com/video/76979871?h=a1b2c3d4e5")])
def test_a_provider_url_is_shown_through_its_privacy_embed(url: str, embed_url: str) -> None:
    got = embed.video_of(vid(url))
    assert got is not None and got.embed_url == embed_url and got.url == url and got.start == 0


def test_an_unlisted_vimeo_hash_stays_ahead_of_the_start() -> None:
    got = embed.video_of(vid("https://vimeo.com/76979871/a1b2c3d4e5", start=90))
    assert got is not None and got.embed_url == "https://player.vimeo.com/video/76979871?h=a1b2c3d4e5#t=90s"


def test_a_start_time_is_a_field_and_rides_on_the_embed() -> None:
    yt = embed.video_of(vid("https://youtu.be/dQw4w9WgXcQ", start=90))
    vm = embed.video_of(vid("https://vimeo.com/76979871", start=90))
    assert yt is not None and yt.provider == "youtube" and yt.start == 90 and yt.embed_url.endswith("embed/dQw4w9WgXcQ?start=90")
    assert vm is not None and vm.provider == "vimeo" and vm.embed_url.endswith("video/76979871#t=90s")


@pytest.mark.parametrize("url", ["https://a.example/v.mp4", "https://a.example/d/v.webm?x=1", "https://a.example/V.OGV"])
def test_a_direct_media_url_is_a_file(url: str) -> None:
    got = embed.video_of(vid(url, start=3))
    assert got is not None and got.provider == "file" and got.embed_url == url and got.start == 3


@pytest.mark.parametrize("text", [
    "https://youtu.be/dQw4w9WgXcQ", "[]", "not json", "{}", vid(3), vid("http://youtu.be/dQw4w9WgXcQ"),
    vid("https://youtu.be/short"), vid("https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ"),
    vid("https://www.youtube.com/watch"), vid("https://vimeo.com/notanumber"),
    vid("https://vimeo.com/\u0667\u0666"), vid("https://vimeo.com/76979871/bad hash"),
    vid("https://vimeo.com/76979871/a1b2c3d4e5/extra"), vid("https://vimeo.com/76979871/xyz"), vid("https://a.example/page"),
    vid("https://a.example/v.mp4", start=-1), vid("https://a.example/v.mp4", start=1.5),
    vid("https://a.example/v.mp4", start=True), vid("https://a.example/v.mp4", start=10**7),
    vid("https://a.example/v.mp4", autoplay=True), vid("https://user@a.example/v.mp4")])
def test_a_video_body_outside_that_shape_is_refused(text: str) -> None:
    assert embed.video_of(text) is None and not embed.video_well_formed(text)


def test_an_empty_video_body_is_a_draft() -> None:
    assert embed.video_well_formed("") and embed.video_of("") is None


@pytest.mark.parametrize("url, start", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90", 90), ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s", 90),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1h2m3s", 3723), ("https://youtu.be/dQw4w9WgXcQ?t=2m", 120),
    ("https://youtu.be/dQw4w9WgXcQ?start=45", 45), ("https://vimeo.com/76979871#t=90s", 90),
    ("https://vimeo.com/76979871#t=1m30s", 90), ("https://vimeo.com/76979871/a1b2c3d4e5#t=30", 30)])
def test_a_start_in_the_url_is_the_start_when_the_body_has_none(url: str, start: int) -> None:
    got = embed.video_of(vid(url))
    assert got is not None and got.start == start and got.url == url
    assert (f"start={start}" in got.embed_url) or (f"#t={start}s" in got.embed_url)


def test_an_explicit_start_wins_over_the_urls() -> None:
    got = embed.video_of(vid("https://youtu.be/dQw4w9WgXcQ?t=90", start=5))
    assert got is not None and got.start == 5 and got.embed_url.endswith("?start=5")
    zero = embed.video_of(vid("https://youtu.be/dQw4w9WgXcQ?t=90", start=0))
    assert zero is not None and zero.start == 0


@pytest.mark.parametrize("t", ["x", "-5", "1.5", "1h2", "s", "", "99999999", "\u0667"])
def test_a_start_in_the_url_that_is_not_a_time_is_ignored(t: str) -> None:
    got = embed.video_of(vid(f"https://youtu.be/dQw4w9WgXcQ?t={t}"))
    assert got is not None and got.start == 0


def test_a_files_url_start_is_not_read() -> None:
    got = embed.video_of(vid("https://a.example/v.mp4?t=30"))
    assert got is not None and got.start == 0


def test_whitespace_around_the_video_url_is_trimmed() -> None:
    got = embed.video_of(vid("  https://youtu.be/dQw4w9WgXcQ\n"))
    assert got is not None and got.url == "https://youtu.be/dQw4w9WgXcQ"
    assert embed.video_of(vid("https://youtu.be/dQw4w9WgXcQ extra")) is None


@pytest.mark.parametrize("text", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "https://m.youtube.com/results?search_query=tsp",
    "https://www.youtube.com/results?search_query=Reducible+The+Traveling+Salesman+Problem", "https://vimeo.com/76979871",
    "https://player.vimeo.com/video/76979871"])
def test_a_page_of_a_video_provider_is_a_video_piece_never_a_site_piece(text: str) -> None:
    assert not embed.site_well_formed(text)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/results?search_query=Reducible+TSP", "https://www.youtube.com/@Reducible",
    "https://www.youtube.com/playlist?list=PLZ", "https://vimeo.com/search?q=tsp", "https://vimeo.com/channels/staffpicks"])
def test_a_video_piece_without_a_video_id_is_refused(url: str) -> None:
    assert not embed.video_well_formed(json.dumps({"url": url}))
    assert embed.video_well_formed(json.dumps({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}))
