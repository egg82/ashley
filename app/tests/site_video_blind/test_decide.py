"""`decide` and the site and video kinds: an Add or Edit whose body is not well formed is refused `bad_site` or
`bad_video`, after `too_long`, and a refusal still takes its seq and changes nothing."""

import json
from types import MappingProxyType

import pytest
from ashley.workshop.commands import Added, Edited
from ashley.workshop.embed import Video, video_of
from ashley.workshop.decide import EMPTY, Accepted, Decision, Refused, decide
from ashley.workshop.model import By, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.commands import Add, Edit, Undo

ALANA = By(7)
SITE = Kind("site", "live", "Site", 200, "site")
VIDEO = Kind("video", "live", "Video", 300, "video")
NOTE = Kind("note", "stored", "Note", 200, "plain")
DOC = Kind("document", "stored", "Document", 200, "markdown")
RULES = Rules(MappingProxyType({"site": SITE, "video": VIDEO, "note": NOTE, "document": DOC}), 10, 20, 10, 100)

GOOD_SITE = "https://example.com/a"
GOOD_VIDEO = json.dumps({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "start": 12})


def add(kind: str, body: str, title: str = "t") -> Add:
    return Add(ALANA, kind, Text(title, body), "small")


def run(*commands: Add | Edit | Undo) -> list[Decision]:
    state = EMPTY
    out: list[Decision] = []
    for c in commands:
        d = decide(state, c, RULES)
        out.append(d)
        state = d.state
    return out


def reason_of(d: Decision) -> str:
    assert isinstance(d, Refused), f"expected a refusal, got {d}"
    return d.reason


@pytest.mark.parametrize(("kind", "body", "why"), [
    ("site", "http://example.com", "bad_site"), ("site", "javascript:alert(1)", "bad_site"),
    ("site", "https://u:p@example.com", "bad_site"), ("site", "two https://a.example https://b.example", "bad_site"),
    ("site", "example.com", "bad_site"), ("site", GOOD_VIDEO, "bad_site"),
    ("video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "bad_video"), ("video", "junk", "bad_video"),
    ("video", json.dumps({"url": "https://www.youtube.com.evil.example/watch?v=x", "start": 0}), "bad_video"),
    ("video", json.dumps({"url": "http://cdn.example.com/a.mp4", "start": 0}), "bad_video"),
    ("video", json.dumps({"url": "https://cdn.example.com/a.mp4", "start": -3}), "bad_video"),
    ("video", json.dumps({"url": "https://cdn.example.com/a.mp4", "start": 1.5}), "bad_video"),
    ("video", GOOD_SITE, "bad_video"),
])
def test_an_add_of_a_malformed_body_is_refused_by_its_kind(kind: str, body: str, why: str) -> None:
    (d,) = run(add(kind, body))
    assert reason_of(d) == why and d.state.pieces == () and d.seq == 1


@pytest.mark.parametrize(("kind", "body"), [("site", ""), ("site", GOOD_SITE), ("video", ""), ("video", GOOD_VIDEO),
                                            ("video", json.dumps({"url": "https://cdn.example.com/a.mp4"}))])
def test_an_empty_or_well_formed_body_is_added_verbatim(kind: str, body: str) -> None:
    (d,) = run(add(kind, body))
    assert isinstance(d, Accepted) and isinstance(d.effect, Added)
    assert d.state.pieces[0].text == Text("t", body) and d.state.pieces[0].kind == kind


@pytest.mark.parametrize("kind", ["note", "document"])
def test_other_kinds_take_any_body(kind: str) -> None:
    (d,) = run(add(kind, "http://not a url {"))
    assert isinstance(d, Accepted)


@pytest.mark.parametrize(("kind", "bad", "good", "why"), [("site", "http://example.com", GOOD_SITE, "bad_site"),
                                                          ("video", "junk", GOOD_VIDEO, "bad_video")])
def test_an_edit_is_checked_like_an_add_and_a_refusal_leaves_the_piece(kind: str, bad: str, good: str, why: str) -> None:
    first = "" if kind == "site" else GOOD_VIDEO
    a, e1, e2 = run(add(kind, first), Edit(ALANA, 1, 1, Text("t2", bad)), Edit(ALANA, 1, 1, Text("t2", good)))
    assert reason_of(e1) == why and e1.seq == 2
    assert e1.state.pieces == a.state.pieces
    assert isinstance(e2, Accepted) and isinstance(e2.effect, Edited)
    assert e2.state.pieces[0].text == Text("t2", good) and e2.state.pieces[0].version == 2


def test_an_edit_back_to_empty_is_a_draft_and_accepted() -> None:
    _, e = run(add("site", GOOD_SITE), Edit(ALANA, 1, 1, Text("t", "")))
    assert isinstance(e, Accepted)


def test_an_undone_edit_of_a_site_restores_its_earlier_body() -> None:
    _, _, u = run(add("site", GOOD_SITE), Edit(ALANA, 1, 1, Text("t", "https://example.org/b")), Undo(ALANA, 2))
    assert isinstance(u, Accepted) and u.state.pieces[0].text == Text("t", GOOD_SITE)


def test_too_long_is_judged_before_the_body_is_checked() -> None:
    assert reason_of(run(add("site", "http://" + "a" * 300))[0]) == "too_long"
    assert reason_of(run(add("video", "junk" * 100))[0]) == "too_long"
    long_good = "https://example.com/" + "a" * 200
    assert reason_of(run(add("site", long_good))[0]) == "too_long"
    _, e = run(add("site", GOOD_SITE), Edit(ALANA, 1, 1, Text("t", "http://" + "a" * 300)))
    assert reason_of(e) == "too_long"


def test_a_refusal_for_one_kind_does_not_name_the_other() -> None:
    assert reason_of(run(add("site", "junk"))[0]) == "bad_site"
    assert reason_of(run(add("video", "junk"))[0]) == "bad_video"


WHITESPACE_SITES = [" " + GOOD_SITE, GOOD_SITE + "\n", "\t" + GOOD_SITE + "\u00a0", "\u3000" + GOOD_SITE + "\u2028"]


@pytest.mark.parametrize("raw", WHITESPACE_SITES)
def test_a_sites_surrounding_whitespace_is_stored_trimmed_on_add_and_on_edit(raw: str) -> None:
    (added,) = run(add("site", raw))
    assert isinstance(added, Accepted) and added.state.pieces[0].text == Text("t", GOOD_SITE)
    _, edited = run(add("site", ""), Edit(ALANA, 1, 1, Text("t", raw)))
    assert isinstance(edited, Accepted) and edited.state.pieces[0].text == Text("t", GOOD_SITE)


@pytest.mark.parametrize("raw", [" ", "\n", "\r", "\t \n"])
def test_a_whitespace_only_body_is_stored_as_the_empty_body(raw: str) -> None:
    for kind in ("site", "video"):
        (d,) = run(add(kind, raw))
        assert isinstance(d, Accepted) and d.state.pieces[0].text == Text("t", "")


def test_a_videos_body_and_url_are_stored_trimmed() -> None:
    (d,) = run(add("video", "\n" + GOOD_VIDEO + " \n"))
    assert isinstance(d, Accepted) and d.state.pieces[0].text == Text("t", GOOD_VIDEO)
    spaced = json.dumps({"url": " https://www.youtube.com/watch?v=dQw4w9WgXcQ\n", "start": 12})
    (d,) = run(add("video", spaced))
    assert isinstance(d, Accepted) and json.loads(d.state.pieces[0].text.body) == json.loads(GOOD_VIDEO)


def test_a_url_start_is_the_start_only_when_the_body_gives_none() -> None:
    assert video_of(json.dumps({"url": "https://youtu.be/dQw4w9WgXcQ?t=1h2m3s"})) == Video(
        "youtube", "https://youtu.be/dQw4w9WgXcQ?t=1h2m3s", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=3723", 3723)
    got = video_of(json.dumps({"url": "https://vimeo.com/76979871#t=90s", "start": 5}))
    assert got is not None and got.start == 5
