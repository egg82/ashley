"""Contract 8, the web: `ChatConversationTurn.receipts` is the stored snapshot, the Agree rule is as it was, and the
snapshot outlives the proposal. `ChatReply` and `MessageResponse` carry the reply's receipts too."""

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import pytest
from ashley.channels.model import Inbound, Outbound
from ashley.conversations.model import Receipts
from contract.conversations_support import run
from receipts_blind_support import WIRE_RAN, json_receipts, same_json
from receipts_blind_wire_support import (DONE_ONLY, OK_TEXT, RECEIPTS, Site, conversation, device_client, open_app,
                                         turn)


def wire_of(receipts: Receipts | None) -> object:
    return json_receipts(receipts)


def test_c08_her_turn_serves_the_stored_snapshot_and_a_turn_without_serves_null(page: Site) -> None:
    turns = page.turns()
    assert same_json(turns[1]["receipts"], wire_of(RECEIPTS))
    assert [t["receipts"] for t in turns if t["id"] != 2] == [None, None, None]
    assert all("receipts" in t for t in turns)


def test_c08_the_wire_names_done_held_and_the_proposal_and_each_receipt_its_three_parts(page: Site) -> None:
    got = page.turns()[1]["receipts"]
    assert set(got) == {WIRE_RAN, "held", "proposal_id", "choice_rows"} and got["proposal_id"] == RECEIPTS.proposal_id
    assert all(set(r) == {"headline", "detail", "why"} for r in (*got[WIRE_RAN], *got["held"]))
    assert got[WIRE_RAN][0]["why"] == "RB-why-1" and got["held"][0]["why"] is None


def test_c08_her_text_on_the_wire_is_only_her_words(page: Site) -> None:
    assert page.turns()[1]["text"] == OK_TEXT


def test_c08_agree_is_offered_on_the_answer_the_proposal_was_held_in_and_nowhere_else(page: Site) -> None:
    number = run_one(page.hold(1))
    turns = page.turns()
    assert [t["agree"] for t in turns] == [None, number, None, None]
    assert turns[1]["receipts"] is not None


def test_c08_the_snapshot_survives_the_proposal_being_deleted(page: Site) -> None:
    run_one(page.hold(1))
    page.proposals.rows.clear()
    after = page.turns()[1]
    assert after["agree"] is None and same_json(after["receipts"], wire_of(RECEIPTS))


def test_c08_the_snapshot_survives_the_proposal_being_taken(page: Site) -> None:
    run_one(page.hold(1))
    run_one(page.take(3))
    after = page.turns()[1]
    assert after["agree"] is None and same_json(after["receipts"], wire_of(RECEIPTS))


def test_c08_a_snapshot_with_nothing_held_offers_no_agree() -> None:
    for page in open_app(conversation(turn(1, "person", "do it"), turn(2, "ashley", OK_TEXT, DONE_ONLY, answers=1))):
        turns = page.turns()
        assert turns[1]["agree"] is None and turns[1]["receipts"]["proposal_id"] is None
        assert turns[1]["receipts"]["held"] == [] and turns[1]["receipts"][WIRE_RAN][0]["detail"] is None


def run_one[T](work: Coroutine[Any, Any, T]) -> T:
    got: list[T] = []

    async def go() -> None:
        got.append(await work)

    run(go())
    return got[0]


def reply_with(receipts: Receipts | None) -> Callable[[Inbound], Awaitable[Outbound]]:
    async def respond(inbound: Inbound) -> Outbound:
        return Outbound(5, "text", OK_TEXT, receipts=receipts)

    return respond


@pytest.mark.parametrize("sent", [RECEIPTS, None])
def test_c08_a_web_reply_carries_the_receipts_it_was_given_or_null(monkeypatch: pytest.MonkeyPatch, sent: Receipts | None) -> None:
    monkeypatch.setattr("ashley.api.chat.respond", reply_with(sent))
    for page in open_app(conversation(turn(1, "person", "hi"))):
        body = page.client.post("/api/chat/messages", json={"text": "hi"}).json()
        assert body["body"] == OK_TEXT and "receipts" in body
        assert same_json(body["receipts"], wire_of(sent))


@pytest.mark.parametrize("sent", [RECEIPTS, None])
def test_c08_a_device_reply_carries_the_receipts_it_was_given_or_null(
        monkeypatch: pytest.MonkeyPatch, sent: Receipts | None) -> None:
    monkeypatch.setattr("ashley.api.messages.respond", reply_with(sent))
    body = device_client().post("/api/messages", json={"text": "hi"}).json()
    assert body["body"] == OK_TEXT
    assert ("receipts" in body) == (sent is not None), "the device contract omits an absent field, as it always has"
    assert same_json(body.get("receipts"), wire_of(sent))
