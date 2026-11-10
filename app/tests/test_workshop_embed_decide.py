"""Site and video pieces through `decide`: an Add or Edit whose body is not empty and not the kind's shape is refused
`bad_site` or `bad_video` (after `too_long`); they are not runnable or installable."""

import json

import pytest
from ashley.workshop import rules
from ashley.workshop.commands import Add, Edit, Run
from ashley.workshop.decide import Accepted, Refused, replay
from ashley.workshop.model import By, Text

ALANA = By(7)
RULES = rules.load()
YT = json.dumps({"url": "https://youtu.be/dQw4w9WgXcQ", "start": 5})


def add(kind: str, body: str) -> Add:
    return Add(ALANA, kind, Text("t", body), "small")


def last(*commands: Add | Edit | Run) -> object:
    return replay(commands, RULES)[-1]


def test_the_kinds_are_live_and_say_their_format() -> None:
    assert (RULES.kinds["site"].family, RULES.kinds["site"].format) == ("live", "site")
    assert (RULES.kinds["video"].family, RULES.kinds["video"].format) == ("live", "video")


@pytest.mark.parametrize("kind, body", [("site", ""), ("site", "https://a.example/x"), ("video", ""), ("video", YT)])
def test_a_body_of_the_kinds_shape_is_accepted_on_add_and_edit(kind: str, body: str) -> None:
    assert isinstance(last(add(kind, body)), Accepted)
    assert isinstance(last(add(kind, ""), Edit(ALANA, 1, 1, Text("t", body))), Accepted)


@pytest.mark.parametrize("kind, body, reason", [
    ("site", "http://a.example/", "bad_site"), ("site", "just words", "bad_site"),
    ("video", "https://youtu.be/dQw4w9WgXcQ", "bad_video"), ("video", '{"url": "https://a.example/page"}', "bad_video")])
def test_a_body_outside_the_kinds_shape_is_refused(kind: str, body: str, reason: str) -> None:
    got = last(add(kind, body))
    assert isinstance(got, Refused) and got.reason == reason
    got = last(add(kind, ""), Edit(ALANA, 1, 1, Text("t", body)))
    assert isinstance(got, Refused) and got.reason == reason


def test_a_site_over_its_kinds_length_is_too_long_before_it_is_bad() -> None:
    got = last(add("site", "https://a.example/" + "x" * RULES.kinds["site"].max_chars))
    assert isinstance(got, Refused) and got.reason == "too_long"


def test_a_site_is_not_runnable() -> None:
    got = last(add("site", "https://a.example/"), Run(ALANA, 1, 1, "python"))
    assert isinstance(got, Refused) and got.reason == "not_runnable"


@pytest.mark.parametrize("raw, stored", [
    ("  https://a.example/x\n", "https://a.example/x"), ("\thttps://a.example/x\u00a0", "https://a.example/x"),
    ("   \n", "")])
def test_a_sites_surrounding_whitespace_is_stored_trimmed_on_add_and_edit(raw: str, stored: str) -> None:
    for commands in ([add("site", raw)], [add("site", ""), Edit(ALANA, 1, 1, Text("t", raw))]):
        got = last(*commands)
        assert isinstance(got, Accepted) and got.state.pieces[0].text.body == stored


def test_a_videos_surrounding_whitespace_is_stored_trimmed() -> None:
    got = last(add("video", "\n" + YT + "  \n"))
    assert isinstance(got, Accepted) and got.state.pieces[0].text.body == YT


def test_whitespace_inside_a_sites_url_is_still_refused() -> None:
    got = last(add("site", " https://a.example/x y "))
    assert isinstance(got, Refused) and got.reason == "bad_site"


def test_other_kinds_keep_their_whitespace() -> None:
    got = last(Add(ALANA, "note", Text("t", "  hi\n"), "small"))
    assert isinstance(got, Accepted) and got.state.pieces[0].text.body == "  hi\n"


def test_a_videos_url_field_is_stored_trimmed_too() -> None:
    got = last(add("video", json.dumps({"url": " https://youtu.be/dQw4w9WgXcQ\n", "start": 5})))
    assert isinstance(got, Accepted)
    assert json.loads(got.state.pieces[0].text.body) == {"url": "https://youtu.be/dQw4w9WgXcQ", "start": 5}
