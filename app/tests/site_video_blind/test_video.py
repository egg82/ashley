"""`embed.video_well_formed` and `embed.video_of` from the contract: a JSON body `{"url", "start"}`, YouTube and Vimeo
through their privacy embeds, a direct https media file as `file`, lookalike hosts never taken for a provider, and
no autoplay."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from ashley.workshop.embed import video_of, video_well_formed

YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
ID = "dQw4w9WgXcQ"


def body(url: object, start: object = 0) -> str:
    return json.dumps({"url": url, "start": start})


# --- well formed ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "", body(YT), body(YT, 90), json.dumps({"url": YT}), body("https://youtu.be/" + ID),
    body("https://www.youtube.com/shorts/" + ID), body("https://m.youtube.com/watch?v=" + ID), body("https://youtube.com/watch?v=" + ID),
    body("https://www.youtube.com/watch?v=%s&t=90" % ID), body("https://www.youtube.com/watch?v=%s&start=90" % ID),
    body("https://youtu.be/%s?t=90" % ID), body("https://vimeo.com/76979871"), body("https://player.vimeo.com/video/76979871"),
    body("https://cdn.example.com/a.mp4"), body("https://cdn.example.com/a.webm"), body("https://cdn.example.com/a.ogv"),
    body("https://cdn.example.com/a.m4v"), body("https://cdn.example.com/a.mov"), body("https://cdn.example.com/a/b.mp4?sig=1"),
])
def test_a_video_body_or_an_empty_one_is_well_formed(text: str) -> None:
    assert video_well_formed(text) is True


@pytest.mark.parametrize("text", [
    "not json", "{", "[]", "null", "42", '"https://www.youtube.com/watch?v=x"', "true", "{}", json.dumps({"start": 5}),
    json.dumps({"url": None}), json.dumps({"url": 5, "start": 0}), json.dumps({"url": ["https://cdn.example.com/a.mp4"]}),
    body(""), body("http://cdn.example.com/a.mp4"), body("http://www.youtube.com/watch?v=" + ID),
    body("javascript:alert(1)"), body("data:video/mp4;base64,AAAA"), body("//cdn.example.com/a.mp4"), body("/a.mp4"),
    body("https://user:pw@cdn.example.com/a.mp4"), body("https://user@www.youtube.com/watch?v=" + ID),
    body("https://www.youtube.com@evil.example/watch?v=" + ID), body("https://cdn.example.com/a b.mp4"),
    body("https://example.com/page"), body("https://example.com/"), body("https://cdn.example.com/a.mp4.html"),
    body("https://cdn.example.com/a.txt"), body("https://cdn.example.com/mp4"),
    body("https://www.youtube.com.evil.example/watch?v=" + ID), body("https://evil.example/youtube.com/watch?v=" + ID),
    body("https://evil.example/?u=https://www.youtube.com/watch?v=" + ID), body("https://notyoutube.com/watch?v=" + ID),
    body("https://vimeo.com.evil.example/76979871"), body("https://evil.example/vimeo.com/76979871"),
    body("https://notvimeo.com/76979871"),
    body(YT, -1), body(YT, 1.5), body(YT, "90"), body(YT, True), body(YT, False), body(YT, [90]),
])
def test_anything_but_an_empty_body_or_a_good_video_body_is_refused(text: str) -> None:
    assert video_well_formed(text) is False


def test_well_formed_agrees_with_video_of_on_every_nonempty_body() -> None:
    for text in ["", body(YT), body("https://example.com/page"), "junk", body("https://cdn.example.com/a.mp4", 3)]:
        if text:
            assert video_well_formed(text) is (video_of(text) is not None)


# --- video_of ------------------------------------------------------------------------------------------------------


def test_an_empty_or_malformed_body_has_no_video() -> None:
    assert video_of("") is None and video_of("junk") is None and video_of(body("http://cdn.example.com/a.mp4")) is None


@pytest.mark.parametrize("url", [YT, "https://youtu.be/" + ID, "https://www.youtube.com/shorts/" + ID,
                                 "https://m.youtube.com/watch?v=" + ID, "https://www.youtube.com/watch?v=%s&t=90" % ID,
                                 "https://www.youtube.com/watch?v=%s&start=90" % ID, "https://youtu.be/%s?t=90" % ID])
def test_youtube_forms_embed_through_the_privacy_host(url: str) -> None:
    got = video_of(body(url))
    assert got is not None and got.provider == "youtube" and got.url == url
    embed = urlsplit(got.embed_url)
    assert embed.scheme == "https" and embed.hostname in ("www.youtube-nocookie.com", "youtube-nocookie.com")
    assert embed.path == "/embed/" + ID
    assert embed.username is None and embed.port is None


def test_the_body_start_reaches_the_video_and_the_embed() -> None:
    got = video_of(body(YT, 42))
    assert got is not None and got.start == 42
    assert parse_qs(urlsplit(got.embed_url).query).get("start") == ["42"]


def test_a_missing_start_is_zero() -> None:
    got = video_of(json.dumps({"url": YT}))
    assert got is not None and got.start == 0


def test_start_zero_is_zero() -> None:
    got = video_of(body(YT, 0))
    assert got is not None and got.start == 0


def test_vimeo_embeds_through_the_player_host_with_the_id() -> None:
    for url in ("https://vimeo.com/76979871", "https://player.vimeo.com/video/76979871"):
        got = video_of(body(url, 42))
        assert got is not None and got.provider == "vimeo" and got.url == url and got.start == 42
        embed = urlsplit(got.embed_url)
        assert embed.scheme == "https" and embed.hostname == "player.vimeo.com" and embed.path == "/video/76979871"
        assert "42" in got.embed_url


@pytest.mark.parametrize("suffix", ["mp4", "webm", "ogv", "m4v", "mov"])
def test_a_direct_media_file_is_a_file_and_embeds_as_itself(suffix: str) -> None:
    url = f"https://cdn.example.com/clips/a.{suffix}"
    got = video_of(body(url, 5))
    assert got is not None and (got.provider, got.url, got.embed_url, got.start) == ("file", url, url, 5)


def test_a_media_file_is_known_by_its_path_not_its_query() -> None:
    url = "https://cdn.example.com/a.mp4?sig=abc&x=1"
    got = video_of(body(url))
    assert got is not None and got.provider == "file"
    assert video_of(body("https://cdn.example.com/watch?file=a.mp4")) is None


@pytest.mark.parametrize("url", [
    "https://www.youtube.com.evil.example/watch?v=" + ID, "https://evil.example/youtube.com/watch?v=" + ID,
    "https://evil.example/?next=https://youtu.be/" + ID, "https://notyoutube.com/watch?v=" + ID,
    "https://youtube.com.evil.example/a.mp4", "https://evil.example/youtube.com/a.mp4", "https://youtu.be.evil.example/" + ID,
    "https://vimeo.com.evil.example/76979871", "https://evil.example/vimeo.com/76979871", "https://vimeo.com.evil.example/a.mp4",
])
def test_a_lookalike_host_never_becomes_a_provider(url: str) -> None:
    got = video_of(body(url))
    assert got is None or got.provider == "file"
    if got is not None:
        assert got.embed_url == url and "nocookie" not in got.embed_url and "player.vimeo.com" not in got.embed_url


@pytest.mark.parametrize("url", [
    YT + "&autoplay=1", "https://youtu.be/%s?autoplay=1" % ID, "https://vimeo.com/76979871?autoplay=1",
    "https://player.vimeo.com/video/76979871?autoplay=1", YT, "https://vimeo.com/76979871",
])
def test_nothing_autoplays(url: str) -> None:
    for start in (0, 30):
        got = video_of(body(url, start))
        assert got is not None
        assert "autoplay=1" not in got.embed_url.lower() and "autoplay=true" not in got.embed_url.lower()


@pytest.mark.parametrize("v", ['x"><script>alert(1)</script>', "../../evil", "a/b", "a b", "x&autoplay=1", "a?b", "a#b", 'abcde"fghij', "abcde<fghij", "abcde fghi", "abcde.fghi"])
def test_a_hostile_video_id_cannot_steer_the_embed(v: str) -> None:
    got = video_of(body("https://www.youtube.com/watch?v=" + v))
    if got is None:
        return
    embed = urlsplit(got.embed_url)
    assert embed.hostname in ("www.youtube-nocookie.com", "youtube-nocookie.com")
    assert embed.path.startswith("/embed/") and ".." not in embed.path and embed.path.count("/") == 2
    assert not any(c in got.embed_url for c in '"<> ') and "autoplay" not in got.embed_url


def test_the_video_is_a_value_that_compares_by_content() -> None:
    assert video_of(body(YT, 7)) == video_of(body(YT, 7))
    assert video_of(body(YT, 7)) != video_of(body(YT, 8))


@pytest.mark.parametrize("v", ["", "abc", "dQw4w9WgXc", "dQw4w9WgXcQQ"])
def test_a_youtube_id_is_eleven_characters(v: str) -> None:
    assert video_of(body("https://www.youtube.com/watch?v=" + v)) is None
    assert video_of(body("https://youtu.be/" + v)) is None


def test_a_youtube_page_without_a_video_is_not_a_video() -> None:
    for url in ("https://www.youtube.com/", "https://www.youtube.com/watch", "https://www.youtube.com/@someone",
                "https://vimeo.com/", "https://vimeo.com/about"):
        assert video_of(body(url)) is None


def test_a_vimeo_player_url_keeps_its_id_not_its_word_video() -> None:
    got = video_of(body("https://player.vimeo.com/video/76979871"))
    assert got is not None and urlsplit(got.embed_url).path == "/video/76979871"


@pytest.mark.parametrize("url", [YT + " ", " " + YT, "\n" + YT + "\n", "\t" + YT + "\u00a0"])
def test_whitespace_around_the_url_is_accepted_and_the_url_is_read_trimmed(url: str) -> None:
    assert video_well_formed(body(url)) is True
    got = video_of(body(url))
    assert got is not None and got.url == YT


def test_whitespace_inside_the_url_still_refuses_it() -> None:
    assert video_well_formed(body("https://www.youtube.com/watch?v=" + ID + " &t=3")) is False
