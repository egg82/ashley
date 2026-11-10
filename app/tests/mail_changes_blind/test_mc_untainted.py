"""A change in a turn that has read nothing outside runs (design: "A send or draft in a turn that has read nothing outside
(an email the person dictates) runs, as any change does"; "Rejected: holding every send even in an untainted turn"), once,
with what was asked, through Gmail's own calls."""

import pytest
from mail_changes_blind_support import (DRAFT, SEED_ACCESS, SEND, World, data, failed, labels_now, send_args,
                                        untouched)


def test_a_dictated_send_runs_once_with_what_was_asked(stocked: World) -> None:
    turn = stocked.guarded()
    got = turn.call(SEND, **send_args(to=["dana@club.test", "ella@club.test"], cc=["fay@club.test"],
                                      subject="Saturday plans", body="See you at nine.\nBring chairs."))
    assert not got.is_error, got.content
    assert len(stocked.fake.sent) == 1
    one = stocked.fake.sent[0]
    assert one.to == ("dana@club.test", "ella@club.test") and one.cc == ("fay@club.test",) and one.bcc == ()
    assert one.subject == "Saturday plans" and one.body == "See you at nine.\nBring chairs."
    assert [w.path for w in stocked.fake.writes()] == ["/messages/send"]
    assert set(stocked.fake.bearers()) == {SEED_ACCESS}
    assert turn.tainted is None and turn.pending() == ""
    assert stocked.fake.drafts == []


def test_a_send_does_not_taint_the_turn_so_the_next_change_runs_too(stocked: World) -> None:
    turn = stocked.guarded()
    first = turn.call(SEND, **send_args())
    assert first.outside is not True
    assert not turn.call(SEND, **send_args(subject="Sunday")).is_error
    assert [s.subject for s in stocked.fake.sent] == ["Saturday", "Sunday"]


def test_words_outside_ascii_arrive_as_written(stocked: World) -> None:
    got = stocked.guarded().call(SEND, **send_args(subject="Réunion ☃ à 9h", body="café au lait — 100 %"))
    assert not got.is_error, got.content
    assert stocked.fake.sent[0].subject == "Réunion ☃ à 9h" and stocked.fake.sent[0].body == "café au lait — 100 %"


@pytest.mark.parametrize("tool", [SEND, DRAFT])
def test_a_reply_names_the_message_it_answers_and_its_thread(stocked: World, tool: str) -> None:
    got = stocked.guarded().call(tool, **send_args(reply_to="m1", subject="Re: Hello"))
    assert not got.is_error, got.content
    stored = (stocked.fake.sent if tool == SEND else stocked.fake.drafts)[0]
    assert stored.in_reply_to == "<m1@mail.test>" and stored.thread_id == "th-m1"


@pytest.mark.parametrize("tool", [SEND, DRAFT])
def test_a_reply_to_a_message_the_mailbox_does_not_have_is_not_found_and_stores_nothing(stocked: World, tool: str) -> None:
    before = labels_now(stocked)
    failed(stocked.guarded().call(tool, **send_args(reply_to="ghost")), "not_found")
    untouched(stocked, before)


def test_a_draft_is_stored_in_gmail_and_not_sent(stocked: World) -> None:
    turn = stocked.guarded()
    got = turn.call(DRAFT, **send_args(to=["dana@club.test"], cc=["fay@club.test"], subject="Later", body="Maybe."))
    assert not got.is_error, got.content
    assert stocked.fake.sent == [] and len(stocked.fake.drafts) == 1
    one = stocked.fake.drafts[0]
    assert one.to == ("dana@club.test",) and one.cc == ("fay@club.test",) and one.subject == "Later" and one.body == "Maybe."
    assert [w.path for w in stocked.fake.writes()] == ["/drafts"]
    assert got.outside is not True and turn.tainted is None


def test_a_failed_send_reaches_nobody_and_says_why(stocked: World) -> None:
    stocked.fake.gmail_status = 503
    failed(stocked.guarded().call(SEND, **send_args()), "unreachable")
    assert stocked.fake.sent == []


def test_a_gmail_that_is_down_fails_the_send_as_unreachable(stocked: World) -> None:
    stocked.fake.gmail_down = True
    failed(stocked.guarded().call(SEND, **send_args()), "unreachable")
    assert stocked.fake.sent == []


def test_the_result_of_a_send_is_json_text_and_carries_no_token(stocked: World) -> None:
    got = stocked.guarded().call(SEND, **send_args())
    assert SEED_ACCESS not in got.content
    data(got)
