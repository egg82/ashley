"""Her three mail changes as tools (`mail_draft`, `mail_label`, `mail_send`) over the real Gmail adapter and a fake Gmail:
what each takes and answers, arguments judged before Gmail is asked anything, the gate for changing (a shared mailbox
needs a speaker the channel names; a kept one only its owner alone), and a connection without the scope to change
answering that it must be connected again."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest
from ashley.connections.resources import Use
from ashley.google.kind import GMAIL_READ
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.mail import MailTools
from ashley.tools.tools import Tools
from mail_gmail_support import ALANA, SAM, FakeGmail, connect, message, wire

MILLIS = 1_762_000_000_000
INBOX = [message("a1", "Field trip", MILLIS, ("INBOX", "UNREAD")), message("a2", "Receipt", MILLIS - 5000)]
CHANGES = ["mail_draft", "mail_label", "mail_send"]
WRITTEN = {"to": ["pat@school.test"], "subject": "Form", "body": "Signed."}
LABELLED = {"messages": [{"id": "a1", "from": "Pat <pat@school.test>", "subject": "Field trip"}], "folder": "archive"}


def tools(person: int | None = ALANA, alone: bool = True) -> MailTools:
    return MailTools(Use(1, person, alone), 8000)


def say(source: Tools, name: str, args: Mapping[str, object]) -> ToolResult:
    return asyncio.run(source.call(ToolCall("c", name, args)))


def names(source: Tools) -> list[str]:
    return [s.name for s in asyncio.run(source.catalogue()).specs]


def setup(**kw: Any) -> FakeGmail:
    gmail = FakeGmail([dict(m) for m in INBOX])
    wire(gmail)
    connect(**kw)
    return gmail


def test_a_draft_a_send_and_a_label_answer_with_what_was_made() -> None:
    gmail = setup()
    assert json.loads(say(tools(), "mail_draft", WRITTEN).content) == {"draft": "d1"}
    assert json.loads(say(tools(), "mail_send", WRITTEN).content) == {"sent": "s1"}
    assert json.loads(say(tools(), "mail_label", LABELLED).content) == {"changed": 1}
    assert [p for p, _ in gmail.posted] == ["/drafts", "/messages/send", "/messages/batchModify"]


def test_unread_true_marks_unread_and_false_marks_read() -> None:
    gmail = setup()
    say(tools(), "mail_label", {**LABELLED, "folder": "", "unread": True})
    say(tools(), "mail_label", {**LABELLED, "folder": "", "unread": False})
    assert [(b["addLabelIds"], b["removeLabelIds"]) for _, b in gmail.posted] == [(["UNREAD"], []), ([], ["UNREAD"])]


@pytest.mark.parametrize(("name", "args"), [
    ("mail_send", {**WRITTEN, "to": []}), ("mail_send", {"subject": "x", "body": "x"}),
    ("mail_send", {**WRITTEN, "to": ["not an address"]}), ("mail_send", {**WRITTEN, "to": ["a@b.test, c@d.test"]}),
    ("mail_send", {**WRITTEN, "to": ["Pat <pat@school.test>"]}), ("mail_send", {**WRITTEN, "to": "pat@school.test"}),
    ("mail_send", {**WRITTEN, "cc": ["a@b.test"] * 5}), ("mail_send", {**WRITTEN, "subject": "a\nBcc: x@y.test"}),
    ("mail_send", {**WRITTEN, "body": ""}), ("mail_send", {**WRITTEN, "body": "x" * 2501}),
    ("mail_send", {**WRITTEN, "body": 5}), ("mail_draft", {**WRITTEN, "bcc": ["a@b.test"]}),
    ("mail_label", {**LABELLED, "messages": []}), ("mail_label", {**LABELLED, "messages": LABELLED["messages"] * 9}),
    ("mail_label", {**LABELLED, "messages": [{"id": "a1"}]}), ("mail_label", {"messages": LABELLED["messages"]}),
    ("mail_label", {**LABELLED, "folder": "elsewhere"}), ("mail_label", {**LABELLED, "unread": "yes"}),
    ("mail_label", {**LABELLED, "add": ["x"] * 5}), ("mail_label", {**LABELLED, "add": [""]}),
    ("mail_label", {**LABELLED, "messages": [{"id": "a1", "from": "p" * 101, "subject": "s"}]})])
def test_arguments_are_judged_before_gmail_is_asked_anything(name: str, args: dict[str, object]) -> None:
    gmail = setup()
    got = say(tools(), name, args)
    assert got.is_error and got.content.startswith("bad_arguments")
    assert gmail.seen == []


def test_a_message_that_is_not_the_one_shown_is_refused_and_says_what_was_wrong() -> None:
    gmail = setup()
    wrong = {"messages": [{"id": "a1", "from": "Pat <pat@school.test>", "subject": "Another"}], "folder": "trash"}
    got = say(tools(), "mail_label", wrong)
    assert got.is_error and got.content.startswith("refused") and "sender and subject" in got.content
    assert gmail.posted == []


def test_a_label_that_does_not_exist_is_not_found() -> None:
    setup()
    got = say(tools(), "mail_label", {**LABELLED, "add": ["Nonesuch"]})
    assert got.is_error and got.content.startswith("not_found")


def test_a_connection_that_may_only_read_answers_needs_reconnect_to_each_change() -> None:
    gmail = setup(scopes=("openid", "email", GMAIL_READ))
    assert len(names(tools())) == 7
    for name, args in (("mail_draft", WRITTEN), ("mail_send", WRITTEN), ("mail_label", LABELLED)):
        got = say(tools(), name, args)
        assert got.is_error and got.content.startswith("needs_reconnect") and "connect it again" in got.content
    assert gmail.posted == []
    assert json.loads(say(tools(), "mail_search", {}).content)["messages"]


def test_a_shared_mailbox_is_changed_by_a_housemate_the_channel_names_and_not_by_a_channel_that_names_none() -> None:
    gmail = FakeGmail([dict(m) for m in INBOX])
    wire(gmail)
    connect(shared=True)
    assert names(tools(SAM, alone=False)) == ["mail_boxes", "mail_labels", "mail_search", "mail_read", *CHANGES]
    assert names(tools(None, alone=False)) == ["mail_boxes", "mail_labels", "mail_search", "mail_read"]
    got = say(tools(None, alone=False), "mail_send", WRITTEN)
    assert got.is_error and got.content.startswith("not_connected")
    assert json.loads(say(tools(SAM, alone=False), "mail_send", WRITTEN).content) == {"sent": "s1"}


def test_a_kept_mailbox_is_changed_only_by_its_owner_alone() -> None:
    setup()
    assert names(tools(ALANA, alone=True))[-3:] == CHANGES
    assert names(tools(ALANA, alone=False)) == [] and names(tools(SAM)) == []
    assert say(tools(ALANA, alone=False), "mail_send", WRITTEN).content.startswith("not_connected")


def test_two_mailboxes_each_change_names_one_by_address() -> None:
    wire(FakeGmail(INBOX))
    held = connect(label="one")
    connect(held=held, label="two")
    spec = {s.name: s for s in asyncio.run(tools().catalogue()).specs}["mail_send"]
    assert spec.parameters["required"] == ["to", "body", "mailbox"]
    assert say(tools(), "mail_send", WRITTEN).content.startswith("bad_arguments")
