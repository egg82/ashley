"""Mail by tier behind `Outside` over the real Gmail adapter and a fake Gmail: marking read, adding a household label
and drafting run in a tainted turn; sending and moving to trash are judged, so the Null judge holds them."""

from ashley import services
from ashley.connections.resources import Use
from ashley.inference.model import ToolCall
from ashley.senses.proposals import Proposals
from ashley.tools.mail import MailTools
from ashley.tools.outside import Outside
from mail_gmail_support import ALANA, FakeGmail, connect, message, wire
from taint_tiers_blind_support import CONVERSATION, HOUSEHOLD, STANDING, TURN, Memory, run

MILLIS = 1_762_000_000_000
MESSAGES = [{"id": "a1", "from": "Pat <pat@school.test>", "subject": "Field trip"}]
WRITTEN: dict[str, object] = {"to": ["pat@school.test"], "subject": "Form", "body": "It is signed."}


def turn(tainted: str | None) -> tuple[Outside, FakeGmail, Memory]:
    gmail = FakeGmail([message("a1", "Field trip", MILLIS, ("INBOX", "UNREAD"))])
    wire(gmail)
    connect()
    memory = Memory()
    services.register(Proposals, memory)
    return Outside(MailTools(Use(HOUSEHOLD, ALANA, True), 8000), STANDING, (CONVERSATION, TURN), tainted=tainted), gmail, memory


def paths(gmail: FakeGmail) -> list[str]:
    return [p for p, _ in gmail.posted]


def test_marking_read_adds_a_household_label_and_drafting_run_in_a_tainted_turn() -> None:
    async def go() -> None:
        o, gmail, memory = turn("mail_read")
        await o.catalogue()
        for name, arguments in (("mail_label", {"messages": MESSAGES, "unread": False}),
                                ("mail_label", {"messages": MESSAGES, "add": ["School"]}),
                                ("mail_draft", WRITTEN)):
            got = await o.call(ToolCall("c", name, arguments))
            assert not got.is_error and "held" not in got.content, got.content
        assert len(gmail.posted) == 3 and "/messages/send" not in paths(gmail)
        assert memory.rows == {}

    run(go())


def test_sending_and_moving_to_trash_are_held_in_a_tainted_turn() -> None:
    async def go() -> None:
        o, gmail, memory = turn("mail_read")
        await o.catalogue()
        sent = await o.call(ToolCall("c", "mail_send", WRITTEN))
        trashed = await o.call(ToolCall("c", "mail_label", {"messages": MESSAGES, "folder": "trash"}))
        assert "held" in sent.content and "held" in trashed.content and gmail.posted == []
        [kept] = memory.rows.values()
        assert [c.tool for c in kept.payload.calls] == ["mail_send", "mail_label"]

    run(go())


def test_the_same_changes_all_run_in_an_untainted_turn() -> None:
    async def go() -> None:
        o, gmail, _ = turn(None)
        await o.catalogue()
        await o.call(ToolCall("c", "mail_send", WRITTEN))
        await o.call(ToolCall("c", "mail_label", {"messages": MESSAGES, "folder": "trash"}))
        assert paths(gmail) == ["/messages/send", "/messages/batchModify"]

    run(go())
