"""The `session` kind, the shipped kinds' live reference to a Claude Code session: its body is exactly `{"source": "herdr",
"session": "<id>"}` or empty, anything else is refused `bad_session` on Add and Edit by her or a person, and the body
carries the session's id and nothing of its screen."""

import json

import pytest
from ashley.workshop import rules as workshop_rules, session_piece
from ashley.workshop.commands import Add, Edit
from ashley.workshop.decide import EMPTY, Accepted, Refused, decide
from ashley.workshop.model import HER, By, Text

RULES = workshop_rules.load()
ID = "0a1b2c3d-0000-4000-8000-00000000abcd"
BODY = json.dumps({"source": "herdr", "session": ID})


def add(body: str, by: By = HER) -> Accepted | Refused:
    return decide(EMPTY, Add(by, "session", Text("Parser fix", body), "medium"), RULES)


def test_the_shipped_session_kind_is_live_and_not_outside() -> None:
    kind = RULES.kinds["session"]
    assert (kind.family, kind.format, kind.outside, kind.by_code) == ("live", "session", False, False)
    assert len(BODY) <= kind.max_chars


@pytest.mark.parametrize("by", [HER, By(7)])
def test_her_or_a_person_puts_a_session_up_by_its_reference(by: By) -> None:
    got = add(BODY, by)
    assert isinstance(got, Accepted) and got.state.pieces[0].text.body == BODY
    assert session_piece.reference_of(BODY) == session_piece.SessionRef("herdr", ID)


def test_an_empty_body_is_a_draft() -> None:
    assert isinstance(add(""), Accepted) and isinstance(add("  "), Accepted)


@pytest.mark.parametrize("body", [
    "not json",
    json.dumps([ID]),
    json.dumps({"session": ID}),
    json.dumps({"source": "tmux", "session": ID}),
    json.dumps({"source": "herdr", "session": ID, "text": "a screen"}),
    json.dumps({"source": "herdr", "session": ID.upper()}),
    json.dumps({"source": "herdr", "session": ID[:-1]}),
    json.dumps({"source": "herdr", "session": "../" + ID[3:]}),
    json.dumps({"source": "herdr", "session": 7}),
])
def test_anything_else_is_refused_bad_session(body: str) -> None:
    got = add(body)
    assert isinstance(got, Refused) and got.reason == "bad_session"
    assert session_piece.reference_of(body) is None


def test_an_edit_is_checked_the_same_way() -> None:
    added = add(BODY)
    assert isinstance(added, Accepted)
    bad = decide(added.state, Edit(By(7), 1, 1, Text("Parser fix", '{"source": "herdr"}')), RULES)
    assert isinstance(bad, Refused) and bad.reason == "bad_session"
    other = json.dumps({"source": "herdr", "session": ID.replace("abcd", "ffff")})
    assert isinstance(decide(added.state, Edit(HER, 1, 1, Text("Other", other)), RULES), Accepted)
