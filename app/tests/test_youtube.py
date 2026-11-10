"""What a watch page publishes, read from the captured page: the video's details, the links in its description numbered
by the caller, and the YouTube id of an address from its parsed host and path."""

import pytest

from ashley.tools import page_fetch, youtube
from ashley.workshop.embed import youtube_id_of
from youtube_read_support import PLAYER, VIDEO, WATCH_HTML


def plain(url: str) -> int | None:
    return None


def source(text: str = WATCH_HTML, kind: str = "text/html") -> page_fetch.Source:
    return page_fetch.Source(kind, text, len(text))


def test_the_player_response_is_the_object_the_page_assigns() -> None:
    player = youtube.player_response(WATCH_HTML)
    assert player is not None and player["videoDetails"]["videoId"] == VIDEO


def test_a_page_without_one_or_cut_off_inside_it_has_none() -> None:
    assert youtube.player_response("<p>hello</p>") is None
    assert youtube.player_response(WATCH_HTML[:WATCH_HTML.index("captionTracks")]) is None


def test_the_details_are_title_channel_date_length_and_the_whole_description() -> None:
    text = youtube.details_text(PLAYER, plain)
    assert text is not None
    lines = text.split("\n")
    assert lines[:4] == ["Title: I Found a Bug in the Bread Investigation", "Channel: Loaf Lab",
                         "Published: 2026-10-31", "Length: 9:47"]
    assert lines[4] == "Description:"
    assert text.endswith(PLAYER["videoDetails"]["shortDescription"].strip())
    assert "https://www.youtube.com/watch?v=Qw3rTy7UiOp&t=531s" in text


def test_each_https_link_in_the_description_is_followed_by_the_number_the_caller_gives_it() -> None:
    asked: list[str] = []

    def number(url: str) -> int | None:
        asked.append(url)
        return None if url.endswith("/skip") else len(asked) + 10

    player = {"videoDetails": {"title": "T", "shortDescription":
                               "Code: https://pastebin.com/Zx9Qw3Lm.\nSee (https://a.example/x), http://plain.example/y and "
                               "https://a.example/skip\nend"}}
    text = youtube.details_text(player, number)
    assert text is not None
    assert asked == ["https://pastebin.com/Zx9Qw3Lm", "https://a.example/x", "https://a.example/skip"]
    assert text.endswith("Code: https://pastebin.com/Zx9Qw3Lm (result 11).\nSee (https://a.example/x (result 12)), "
                         "http://plain.example/y and https://a.example/skip\nend")


def test_the_captured_descriptions_own_link_is_numbered() -> None:
    text = youtube.details_text(PLAYER, lambda url: 7)
    assert text is not None and "https://www.youtube.com/watch?v=Qw3rTy7UiOp&t=531s (result 7)" in text


def test_a_player_response_without_a_title_has_no_details() -> None:
    assert youtube.details_text({"videoDetails": {"shortDescription": "x"}}, plain) is None
    assert youtube.details_text({}, plain) is None


def test_the_read_page_of_a_watch_page_is_its_details_not_its_stripped_html() -> None:
    page = youtube.read_page(source(), plain)
    assert page.text.startswith("Title: I Found a Bug") and "ytInitialPlayerResponse" not in page.text
    assert page.title == "I Found a Bug in the Bread Investigation" and page.bytes == len(WATCH_HTML)


def test_a_page_with_no_player_response_reads_as_any_page() -> None:
    page = youtube.read_page(source("<html><head><title>Hi</title></head><body><p>hello</p></body></html>"), plain)
    assert page.text.endswith("hello") and page.title == "Hi"


@pytest.mark.parametrize("url,ident", [
    (f"https://www.youtube.com/watch?v={VIDEO}", VIDEO), (f"https://youtube.com/watch?v={VIDEO}&t=90s", VIDEO),
    (f"https://m.youtube.com/watch?v={VIDEO}", VIDEO), (f"https://youtu.be/{VIDEO}?t=5", VIDEO),
    (f"https://www.youtube.com/shorts/{VIDEO}", VIDEO), (f"https://www.youtube.com/embed/{VIDEO}", VIDEO),
    (f"  https://www.youtube.com/watch?v={VIDEO}  ", VIDEO),
    ("https://www.youtube.com/results?search_query=bread", None), ("https://www.youtube.com/@loaflab", None),
    (f"https://www.youtube.com.evil.example/watch?v={VIDEO}", None), (f"https://evil.example/watch?v={VIDEO}", None),
    (f"https://evil.example/?next=https://www.youtube.com/watch?v={VIDEO}", None),
    (f"http://www.youtube.com/watch?v={VIDEO}", None), ("https://www.youtube.com/watch?v=short", None)])
def test_the_video_an_address_is_the_page_of_comes_from_its_host_and_path(url: str, ident: str | None) -> None:
    assert youtube_id_of(url) == ident
