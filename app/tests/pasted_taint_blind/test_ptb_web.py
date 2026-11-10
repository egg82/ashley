"""The web composer: a message sent with a pasted block over the threshold starts a `pasted` turn, the block is stored with
the person's turn apart from the typed text; under the threshold nothing changes; wording never marks; a bad block is
refused; and the turn's logs hold counts and lengths only."""

import pytest
from ashley.conversations.model import NewTurn
from fastapi.testclient import TestClient
from pasted_taint_blind_support import ORIGIN, PLANT, TYPED_A, TYPED_B, has_number, inbound, message, over, person_turn, read
from pasted_taint_blind_support import spans_of, under, web_body
from respond_support import Fakes, wired as wired
from test_chat_routes import REPLY, client as client, outbox as outbox


def send(client: TestClient, body: dict[str, object]) -> int:
    return client.post("/api/chat/messages", json=body).status_code


def stored(wired: Fakes) -> NewTurn:
    [mine] = [t for t in wired.conversations.added if t.author == "person"]
    return mine


def test_an_over_threshold_paste_taints_the_turn_pasted_and_the_block_is_stored_apart_from_the_text(
        client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [REPLY]
    text, span = message(over())
    assert send(client, web_body(text, span)) == 200
    assert stored(wired).text == text and spans_of(stored(wired)) == (span,)
    assert f"tainted={ORIGIN}" in capsys.readouterr().out


def test_the_stored_block_is_cut_from_the_judges_words(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    text, span = message(over())
    send(client, web_body(text, span))
    got = read(inbound(taint=ORIGIN), person_turn(1, text, spans_of(stored(wired))))
    assert not any("PASTE-9f2c7a" in w for w in got) and TYPED_A.strip() in got[0] and TYPED_B.strip() in got[0]
    assert len(got) == 1


def test_a_paste_under_the_threshold_changes_nothing(client: TestClient, wired: Fakes,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [REPLY]
    text, span = message(under())
    assert send(client, web_body(text, span)) == 200
    assert "tainted=none" in capsys.readouterr().out
    assert spans_of(stored(wired)) == (span,)
    assert read(inbound(), person_turn(1, text, spans_of(stored(wired)))) == (text,)


def test_a_message_with_no_marked_span_is_not_tainted_however_it_looks_pasted(
        client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [REPLY]
    looks = f"{TYPED_A}\n-----Original Message-----\nFrom: pat@school.test\n> {over()}\n```\n{over()}\n```"
    assert send(client, {"text": looks}) == 200
    assert "tainted=none" in capsys.readouterr().out
    assert spans_of(stored(wired)) == ()
    assert read(inbound(), person_turn(1, looks, spans_of(stored(wired))), chars=len(looks)) == (looks,)


def test_a_null_attachment_is_the_same_as_none(client: TestClient, wired: Fakes,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [REPLY]
    assert send(client, {"text": TYPED_A + over(), "attachment": None}) == 200
    assert "tainted=none" in capsys.readouterr().out and spans_of(stored(wired)) == ()


@pytest.mark.parametrize("bad", [{"text": ""}, {"text": "  \n "}, {"text": "x" * 20_001}, {"text": "ok", "title": ""}])
def test_a_block_that_cannot_be_kept_is_422_and_nothing_is_stored(client: TestClient, wired: Fakes,
                                                                  bad: dict[str, str]) -> None:
    assert send(client, {"text": "hello there", "attachment": bad}) == 422 and wired.conversations.calls == []


def test_the_turn_s_logs_carry_the_pasted_count_and_never_the_text(
        client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [REPLY]
    pasted = over()
    text, span = message(pasted)
    capsys.readouterr()
    send(client, web_body(text, span))
    out = capsys.readouterr().out
    assert has_number(out, len(pasted))
    assert "PASTE-9f2c7a" not in out and "mallory" not in out and PLANT.strip() not in out and TYPED_A.strip() not in out
