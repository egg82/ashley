"""A draft is an IMAP APPEND to Drafts; a send goes over SMTP with the right envelope, once (design: "draft = APPEND to
Drafts with the right headers; send goes over SMTP"; "A send is posted once and never retried"; ids by `Message-ID`)."""

from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import pytest
from mail_proton_blind_support import (ALANA_ADDRESS, DRAFT, M1, READ, SEARCH, SEND, SUBJECTS, Box, World, data, failed, rows,
                                       stock)

TO, CC = "dana@club.test", "ella@club.test"


def mine(**over: object) -> dict[str, object]:
    base: dict[str, object] = {"mailbox": ALANA_ADDRESS, "to": [TO], "subject": "Saturday", "body": "See you at nine."}
    return {**base, **over}


def parsed(raw: bytes) -> EmailMessage:
    got = message_from_bytes(raw, policy=policy.default)
    assert isinstance(got, EmailMessage)
    return got


def drafted(box: Box) -> list[EmailMessage]:
    return [parsed(m.raw) for m in box.account.present("Drafts")]


def sent(world: World) -> EmailMessage:
    (done,) = world.bridge.smtp.delivered
    return parsed(done.data)


def body_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    assert part is not None
    return str(part.get_content()).strip()


def test_a_draft_is_appended_to_drafts_once_with_its_headers_and_is_not_sent(world: World, alana: Box) -> None:
    got = data(world.turn().call(DRAFT, **mine(cc=[CC], subject="Saturday plans")))
    (msg,) = drafted(alana)
    assert alana.account.commands == [("APPEND", "Drafts")]
    assert ALANA_ADDRESS in str(msg["From"]) and TO in str(msg["To"]) and CC in str(msg["Cc"])
    assert msg["Subject"] == "Saturday plans" and body_of(msg) == "See you at nine." and msg["Date"] and msg["Message-ID"]
    assert "Bcc" not in msg and world.bridge.smtp.delivered == [] and world.bridge.smtp.attempts == 0
    assert alana.account.where(str(msg["Message-ID"])) == ["Drafts"]
    assert str(msg["Message-ID"]).strip("<>") in got["draft"]


def test_a_draft_is_kept_as_a_draft_and_is_listed_and_read_back_by_the_id_it_gave(world: World, alana: Box) -> None:
    ident = data(world.turn().call(DRAFT, **mine()))["draft"]
    assert "\\Draft" in alana.account.folders["Drafts"].copies[0].flags
    (row,) = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="drafts"))
    assert row["id"] == ident and row["folder"] == "drafts" and row["subject"] == "Saturday"
    assert data(world.turn().call(READ, mailbox=ALANA_ADDRESS, id=ident))["text"].strip() == "See you at nine."


def test_two_drafts_have_two_message_ids(world: World, alana: Box) -> None:
    first = data(world.turn().call(DRAFT, **mine()))["draft"]
    second = data(world.turn().call(DRAFT, **mine()))["draft"]
    assert first != second and len(drafted(alana)) == 2


def test_a_reply_draft_is_threaded_under_the_message_it_answers(world: World, alana: Box) -> None:
    stock(alana)
    row = next(r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)) if r["subject"] == SUBJECTS[M1])
    data(world.turn().call(DRAFT, **mine(reply_to=row["id"], subject="Re: " + SUBJECTS[M1])))
    (msg,) = drafted(alana)
    assert M1 in str(msg["In-Reply-To"]) and M1 in str(msg["References"])


def test_a_reply_to_nothing_is_not_found_and_drafts_nothing(world: World, alana: Box) -> None:
    failed(world.turn().call(DRAFT, **mine(reply_to="<nobody@nowhere.test>")), "not_found")
    failed(world.turn().call(SEND, **mine(reply_to="<nobody@nowhere.test>")), "not_found")
    assert drafted(alana) == [] and world.bridge.smtp.delivered == []


def test_a_send_goes_over_smtp_from_the_mailbox_to_each_recipient_and_no_other(world: World, alana: Box) -> None:
    got = data(world.turn().call(SEND, **mine(to=[TO, "fay@club.test"], cc=[CC])))
    (done,) = world.bridge.smtp.delivered
    msg = sent(world)
    assert (done.user, done.mail_from) == (ALANA_ADDRESS, ALANA_ADDRESS)
    assert sorted(done.rcpts) == sorted([TO, "fay@club.test", CC]) and world.bridge.smtp.attempts == 1
    assert ALANA_ADDRESS in str(msg["From"]) and TO in str(msg["To"]) and CC in str(msg["Cc"]) and "Bcc" not in msg
    assert msg["Subject"] == "Saturday" and body_of(msg) == "See you at nine." and msg["Date"] and msg["Message-ID"]
    assert str(msg["Message-ID"]).strip("<>") in got["sent"]


def test_a_send_saves_nothing_itself_so_sent_holds_the_one_copy_bridge_saved(world: World, alana: Box) -> None:
    data(world.turn().call(SEND, **mine()))
    mid = str(sent(world)["Message-ID"])
    assert alana.account.where(mid) == ["Sent"] and len(alana.account.present("Sent")) == 1
    assert alana.account.commands == [] and drafted(alana) == []


def test_a_reply_is_threaded_under_the_message_it_answers(world: World, alana: Box) -> None:
    stock(alana)
    row = next(r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)) if r["subject"] == SUBJECTS[M1])
    data(world.turn().call(SEND, **mine(reply_to=row["id"], to=["pat@school.test"])))
    msg = sent(world)
    assert M1 in str(msg["In-Reply-To"]) and M1 in str(msg["References"])


def test_each_send_has_its_own_message_id(world: World, alana: Box) -> None:
    data(world.turn().call(SEND, **mine()))
    data(world.turn().call(SEND, **mine()))
    first, second = (parsed(d.data)["Message-ID"] for d in world.bridge.smtp.delivered)
    assert first and second and first != second


def test_text_that_is_not_ascii_arrives_as_written(world: World, alana: Box) -> None:
    data(world.turn().call(SEND, **mine(subject="Café – 5€", body="naïve über ☃")))
    msg = sent(world)
    assert msg["Subject"] == "Café – 5€" and body_of(msg) == "naïve über ☃"
    data(world.turn().call(DRAFT, **mine(subject="Café – 5€", body="naïve")))
    (msg,) = drafted(alana)
    assert msg["Subject"] == "Café – 5€" and body_of(msg) == "naïve"


def test_a_body_line_that_is_one_dot_survives_smtp_transparency(world: World, alana: Box) -> None:
    data(world.turn().call(SEND, **mine(body="before\n.\nafter")))
    assert body_of(sent(world)).splitlines() == ["before", ".", "after"]


@pytest.mark.parametrize("field", ["subject", "to", "cc", "reply_to"])
def test_a_line_break_in_a_header_value_adds_no_header_and_no_recipient(world: World, alana: Box, field: str) -> None:
    evil = "x@y.test\r\nBcc: evil@evil.test" if field in ("to", "cc") else "Hi\r\nBcc: evil@evil.test"
    value: Any = [evil] if field in ("to", "cc") else evil
    got = world.turn().call(SEND, **mine(**{field: value}))
    for delivered in world.bridge.smtp.delivered:
        assert "evil@evil.test" not in delivered.rcpts and "evil@evil.test" not in str(parsed(delivered.data)["Bcc"] or "")
        assert parsed(delivered.data)["Bcc"] is None
    assert got.is_error or world.bridge.smtp.delivered


def test_a_send_with_no_recipient_is_refused_and_sends_nothing(world: World, alana: Box) -> None:
    failed(world.turn().call(SEND, **mine(to=[])))
    assert world.bridge.smtp.attempts == 0


def test_a_recipient_the_server_refuses_fails_the_send_once_and_saves_nothing(world: World, alana: Box) -> None:
    world.bridge.smtp_behaviour.refuse_rcpt = {TO}
    failed(world.turn().call(SEND, **mine()), "refused")
    assert world.bridge.smtp.delivered == [] and alana.account.present("Sent") == [] and world.bridge.smtp.attempts <= 1


def test_a_server_that_fails_the_data_is_one_attempt_and_an_error(world: World, alana: Box) -> None:
    world.bridge.smtp_behaviour.data_code = 451
    failed(world.turn().call(SEND, **mine()), "unreachable", "refused")
    assert world.bridge.smtp.attempts == 1 and world.bridge.smtp.delivered == []


def test_a_send_cut_off_after_the_data_is_unreachable_and_never_retried(world: World, alana: Box) -> None:
    world.bridge.smtp_behaviour.drop_after_data = True
    failed(world.turn().call(SEND, **mine()), "unreachable")
    assert world.bridge.smtp.attempts == 1


def test_a_send_does_not_touch_the_mailbox_over_imap(world: World, alana: Box) -> None:
    stock(alana)
    before = alana.account.logins
    data(world.turn().call(SEND, **mine()))
    assert alana.account.commands == [] and alana.account.logins - before <= 1
