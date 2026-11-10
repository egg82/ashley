"""Gmail's side of her mail changes (`GmailMailbox.draft`, `send` and `change`) over a fake Gmail at its HTTP boundary: the
raw message a draft becomes, a reply threaded under its original, a send made once and never retried, labels resolved
from the mailbox's own list and applied to messages whose sender and subject match, and nothing posted otherwise."""

import asyncio
import base64
import logging
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import pytest
from ashley import services
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Draft, MailChange, MailFailed, Target
from mail_gmail_support import ADDRESS, ALANA, HOME, FakeGmail, connect, message, wire

MILLIS = 1_762_000_000_000
ACCOUNT = Account(1, HOME, ALANA)
INBOX = [message("a1", "Field trip", MILLIS, ("INBOX", "UNREAD")), message("a2", "Receipt", MILLIS - 5000)]
PAT = "Pat <pat@school.test>"


def setup(*, post_status: int | None = None) -> FakeGmail:
    gmail = FakeGmail([dict(m) for m in INBOX], post_status=post_status)
    wire(gmail)
    connect()
    return gmail


def mailbox() -> Mailbox:
    return services.get(Mailbox)


def sent(raw: dict[str, Any]) -> EmailMessage:
    text = raw["raw"]
    parsed = message_from_bytes(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)), policy=policy.default)
    assert isinstance(parsed, EmailMessage)
    return parsed


def failed(coro: Any) -> str:
    with pytest.raises(MailFailed) as e:
        asyncio.run(coro)
    return e.value.reason


def test_a_draft_is_saved_as_the_message_it_describes() -> None:
    gmail = setup()
    made = asyncio.run(mailbox().draft(ACCOUNT, Draft(("pat@school.test",), "Trip form", "It is signed.\nThanks",
                                                       ("sam@home.test",))))
    assert made == "d1"
    (path, body), = gmail.posted
    assert path == "/drafts" and set(body) == {"message"} and "threadId" not in body["message"]
    mail = sent(body["message"])
    assert (mail["To"], mail["Cc"], mail["Subject"]) == ("pat@school.test", "sam@home.test", "Trip form")
    assert mail.get_content().strip().replace("\r\n", "\n") == "It is signed.\nThanks"
    assert gmail.seen[-1][2] == "Bearer ya29.fake-access-token"


def test_a_reply_is_threaded_under_the_message_it_answers() -> None:
    gmail = setup()
    asyncio.run(mailbox().send(ACCOUNT, Draft(("pat@school.test",), "Re: Field trip", "Yes", reply_to="a1")))
    asked = [(p, q.get("format")) for p, q, _ in gmail.seen]
    assert ("/messages/a1", ["metadata"]) in asked
    (path, body), = gmail.posted
    assert path == "/messages/send" and body["threadId"] == "ta1"
    assert sent(body)["In-Reply-To"] == "<m>"


def test_a_send_returns_the_sent_message_and_is_made_once() -> None:
    gmail = setup()
    assert asyncio.run(mailbox().send(ACCOUNT, Draft(("pat@school.test",), "Hello", "Hi"))) == "s1"
    assert [p for p, _ in gmail.posted] == ["/messages/send"]


@pytest.mark.parametrize(("status", "reason"), [(500, "unreachable"), (429, "unreachable"), (403, "refused"),
                                                (400, "refused"), (401, "refused")])
def test_a_send_gmail_fails_is_not_retried_and_says_why(status: int, reason: str) -> None:
    gmail = setup(post_status=status)
    assert failed(mailbox().send(ACCOUNT, Draft(("pat@school.test",), "Hello", "Hi"))) == reason
    assert len(gmail.posted) == 1


def test_a_reply_to_an_unknown_message_is_not_found_and_posts_nothing() -> None:
    gmail = setup()
    assert failed(mailbox().draft(ACCOUNT, Draft(("pat@school.test",), "Re", "Hi", reply_to="nope"))) == "not_found"
    assert failed(mailbox().draft(ACCOUNT, Draft(("pat@school.test",), "Re", "Hi", reply_to="bad id!"))) == "not_found"
    assert gmail.posted == []


def test_a_header_with_a_line_break_is_refused_and_posts_nothing() -> None:
    gmail = setup()
    assert failed(mailbox().send(ACCOUNT, Draft(("pat@school.test",), "Hi\r\nBcc: x@evil.test", "Hi"))) == "refused"
    assert gmail.posted == []


def test_a_change_adds_and_removes_labels_by_name_moves_and_marks_read() -> None:
    gmail = setup()
    targets = (Target("a1", PAT, "Field trip"), Target("a2", "Pat", "Rec"))
    changed = asyncio.run(mailbox().change(ACCOUNT, targets, MailChange(add=("school",), folder="trash", unread=False)))
    assert changed == 2
    (path, body), = gmail.posted
    assert path == "/messages/batchModify" and body["ids"] == ["a1", "a2"]
    assert body["addLabelIds"] == ["Label_7", "TRASH"] and body["removeLabelIds"] == ["INBOX", "SPAM", "UNREAD"]
    assert "TRASH" in gmail.messages[0]["labelIds"] and "INBOX" not in gmail.messages[0]["labelIds"]


@pytest.mark.parametrize(("change", "adds", "removes"), [
    (MailChange(folder="archive"), [], ["INBOX", "SPAM", "TRASH"]), (MailChange(folder="spam"), ["SPAM"], ["INBOX", "TRASH"]),
    (MailChange(folder="inbox"), ["INBOX"], ["SPAM", "TRASH"]), (MailChange(unread=True), ["UNREAD"], []),
    (MailChange(remove=("School",)), [], ["Label_7"])])
def test_each_move_is_the_labels_it_means(change: MailChange, adds: list[str], removes: list[str]) -> None:
    gmail = setup()
    asyncio.run(mailbox().change(ACCOUNT, (Target("a1", PAT, "Field trip"),), change))
    assert (gmail.posted[0][1]["addLabelIds"], gmail.posted[0][1]["removeLabelIds"]) == (adds, removes)


@pytest.mark.parametrize("target", [Target("a1", "Someone <else@evil.test>", "Field trip"),
                                    Target("a1", PAT, "Another subject"), Target("a1", "", "Field trip"),
                                    Target("a2", PAT, "Field trip")])
def test_a_message_that_is_not_the_one_shown_refuses_the_whole_change(target: Target) -> None:
    gmail = setup()
    both = (Target("a2", PAT, "Receipt"), target)
    assert failed(mailbox().change(ACCOUNT, both, MailChange(folder="archive"))) == "refused"
    assert gmail.posted == []


def test_a_message_gone_is_not_found_and_nothing_changes() -> None:
    gmail = setup()
    gmail.gone.add("a2")
    both = (Target("a1", PAT, "Field trip"), Target("a2", PAT, "Receipt"))
    assert failed(mailbox().change(ACCOUNT, both, MailChange(folder="archive"))) == "not_found"
    assert gmail.posted == []


@pytest.mark.parametrize("change", [MailChange(add=("Nonesuch",)), MailChange(add=("TRASH",)), MailChange(add=("INBOX",)),
                                    MailChange(remove=("UNREAD",))])
def test_a_label_that_is_not_one_of_the_households_is_not_found_so_no_system_label_is_reachable_by_name(
        change: MailChange) -> None:
    gmail = setup()
    assert failed(mailbox().change(ACCOUNT, (Target("a1", PAT, "Field trip"),), change)) == "not_found"
    assert gmail.posted == []


def test_a_change_that_changes_nothing_or_contradicts_itself_is_refused() -> None:
    gmail = setup()
    one = (Target("a1", PAT, "Field trip"),)
    assert failed(mailbox().change(ACCOUNT, one, MailChange())) == "refused"
    assert failed(mailbox().change(ACCOUNT, one, MailChange(add=("School",), remove=("School",)))) == "refused"
    assert failed(mailbox().change(ACCOUNT, one, MailChange(folder="elsewhere"))) == "refused"
    assert gmail.posted == []


def test_only_the_modify_scope_may_change() -> None:
    setup()
    adapter = mailbox()

    def can(scopes: tuple[str, ...]) -> bool:
        return adapter.can_change("google", scopes)
    assert can(("openid", "https://www.googleapis.com/auth/gmail.modify")) and can(("https://mail.google.com/",))
    assert not can(("openid", "https://www.googleapis.com/auth/gmail.readonly")) and not can(())


def test_the_calls_log_ids_and_counts_never_what_was_written(caplog: pytest.LogCaptureFixture) -> None:
    setup()
    with caplog.at_level(logging.INFO):
        draft = Draft(("secret-rcpt@school.test",), "Secret subject", "Secret body words")
        asyncio.run(mailbox().draft(ACCOUNT, draft))
        asyncio.run(mailbox().send(ACCOUNT, draft))
        asyncio.run(mailbox().change(ACCOUNT, (Target("a1", PAT, "Field trip"),), MailChange(add=("School",))))
    text = " ".join(repr(r.__dict__.get("fields", "")) + r.getMessage() for r in caplog.records)
    for call in ("draft", "send", "change"):
        assert f"call={call}" in text or f"'call': '{call}'" in text
    for secret in ("secret-rcpt", "Secret subject", "Secret body", "Field trip", "pat@school", ADDRESS, "ya29", "Label_7"):
        assert secret not in text


@pytest.mark.parametrize("status", [500, 503])
def test_a_change_gmail_fails_with_an_empty_answer_is_unreachable(status: int) -> None:
    gmail = setup(post_status=status)
    one = (Target("a1", PAT, "Field trip"),)
    assert failed(mailbox().change(ACCOUNT, one, MailChange(add=("School",)))) == "unreachable"
    assert len(gmail.posted) == 1


def test_a_failed_send_logs_nothing_it_sent_or_was_answered(caplog: pytest.LogCaptureFixture) -> None:
    gmail = setup(post_status=500)
    with caplog.at_level(logging.DEBUG):
        assert failed(mailbox().send(ACCOUNT, Draft(("secret-rcpt@school.test",), "Secret subject", "Secret body"))) == "unreachable"
    raw = gmail.posted[0][1]["raw"]
    text = " ".join(repr(r.__dict__) + r.getMessage() for r in caplog.records)
    assert any(r.getMessage() == "mail.call" for r in caplog.records)
    assert raw[:40] not in text and "secret-rcpt" not in text
