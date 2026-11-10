"""Her mail changes behind `Outside`, over the real Gmail adapter and a fake Gmail: a send the person dictated, in a turn
that has read no outside words, runs once; once `mail_read` has been called the same send is held with its arguments shown
in full, and the person's next message agrees to it with `carry_out`, which runs it once from what was stored."""

import json

from ashley.connections.resources import Use
from ashley.inference.model import ToolCall
from ashley.tools.mail import MailTools
from ashley.tools.outside import CARRY_OUT, Outside
from mail_gmail_support import ALANA, FakeGmail, connect, message, wire
from outside_ask_support import CONVERSATION, HOUSEHOLD, STANDING, TURN, Memory, asked, run
from receipts_shown import held_text
from ashley import services
from ashley.senses.proposals import Proposals

MILLIS = 1_762_000_000_000
SEND: dict[str, object] = {"to": ["pat@school.test"], "subject": "Form", "body": "It is signed."}
LABEL: dict[str, object] = {"messages": [{"id": "a1", "from": "Pat <pat@school.test>", "subject": "Field trip"}], "folder": "trash"}


def turn(gmail: FakeGmail, number: int = TURN, memory: Memory | None = None) -> Outside:
    wire(gmail)
    connect()
    services.register(Proposals, memory or Memory())
    return Outside(MailTools(Use(HOUSEHOLD, ALANA, True), 8000), STANDING, (CONVERSATION, number))


def ask(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall("c", name, arguments)


def inbox() -> FakeGmail:
    return FakeGmail([message("a1", "Field trip", MILLIS, ("INBOX", "UNREAD"))])


def test_a_send_in_an_untainted_private_turn_runs_once() -> None:
    async def go() -> None:
        gmail = inbox()
        outside = turn(gmail)
        got = await outside.call(ask("mail_send", SEND))
        assert json.loads(got.content) == {"sent": "s1"} and not got.is_error
        assert [p for p, _ in gmail.posted] == ["/messages/send"]
        assert outside.tainted is None and await outside.receipts() is None

    run(go())


def test_after_mail_read_the_same_send_is_held_and_runs_once_by_carry_out_with_the_stored_arguments() -> None:
    async def go() -> None:
        gmail, memory = inbox(), Memory()
        outside = turn(gmail, TURN, memory)
        await outside.catalogue()
        assert (await outside.call(asked("mail_read", id="a1"))).is_error is False
        assert outside.tainted == "mail_read"
        held = await outside.call(ask("mail_send", SEND))
        assert "held" in held.content and gmail.posted == []
        block = held_text(await outside.receipts())
        assert "pat@school.test" in block and "Form" in block and "It is signed." in block
        later = Outside(MailTools(Use(HOUSEHOLD, ALANA, True), 8000), STANDING, (CONVERSATION, TURN + 1))
        assert CARRY_OUT in [s.name for s in (await later.catalogue()).specs]
        done = await later.call(asked(CARRY_OUT, "k"))
        assert not done.is_error and "sent" in done.content
        assert [(p, b["raw"] == gmail.posted[0][1]["raw"]) for p, b in gmail.posted] == [("/messages/send", True)]
        again = await later.call(asked(CARRY_OUT, "k2"))
        assert again.is_error and len(gmail.posted) == 1

    run(go())


def test_a_label_after_mail_has_been_read_is_held_and_runs_once_with_the_sender_and_subject_it_showed() -> None:
    async def go() -> None:
        gmail, memory = inbox(), Memory()
        outside = turn(gmail, TURN, memory)
        await outside.catalogue()
        await outside.call(asked("mail_search"))
        await outside.call(ask("mail_label", LABEL))
        assert gmail.posted == []
        block = held_text(await outside.receipts())
        assert "pat@school.test" in block and "Field trip" in block
        later = Outside(MailTools(Use(HOUSEHOLD, ALANA, True), 8000), STANDING, (CONVERSATION, TURN + 1))
        await later.catalogue()
        await later.call(asked(CARRY_OUT, "k"))
        assert [(p, b["ids"]) for p, b in gmail.posted] == [("/messages/batchModify", ["a1"])]

    run(go())


def test_a_draft_after_mail_has_been_read_is_saved_without_asking_and_not_shown_under_the_reply() -> None:
    async def go() -> None:
        gmail = inbox()
        outside = turn(gmail)
        await outside.catalogue()
        await outside.call(asked("mail_read", id="a1"))
        got = await outside.call(ask("mail_draft", SEND))
        assert not got.is_error and [p for p, _ in gmail.posted] == ["/drafts"]
        assert await outside.receipts() is None

    run(go())


def test_a_send_after_mail_has_been_read_is_judged_and_the_null_judge_holds_it() -> None:
    async def go() -> None:
        gmail = inbox()
        outside = turn(gmail)
        await outside.catalogue()
        await outside.call(asked("mail_read", id="a1"))
        got = await outside.call(ask("mail_send", SEND))
        assert "held" in got.content and gmail.posted == []
        receipts = await outside.receipts()
        assert receipts is not None and receipts.done == () and len(receipts.held) == 1

    run(go())
