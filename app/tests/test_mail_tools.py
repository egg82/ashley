"""Her mail tools (`ashley.tools.mail.MailTools`) over the real Gmail adapter and a fake Gmail: offered only to the
person whose connection was granted a read scope, and by `for_turn` only where the reply reaches them alone; the four
tools read as the design says; a connection that needs connecting again answers `needs_reconnect`, never nothing;
and what each tool states about reading and outside words is the design's table."""

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.connections.renewal import NeedsReconnect, Renewal
from ashley.connections.resources import Use
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.mail import MailTools
from ashley.tools.reading import Reading
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from ashley.connections.connections import Connections
from mail_gmail_support import ADDRESS, ALANA, SAM, FakeGmail, FakeRenewal, connect, message, part, wire

MILLIS = 1_762_000_000_000
INBOX = [message("a1", "Field trip", MILLIS, ("INBOX", "UNREAD")), message("a2", "Receipt", MILLIS - 5000)]
CHARS = 8000
WEB = Inbound(household_id=1, thread="person:7:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=ALANA, shared=False, place=None, channel="web", later=True, later_by="turn")


class NoTools(Tools):
    """The household's everyday tools, empty, so a turn's added sources are all that shows."""

    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "none", is_error=True)


def tools(person: int = ALANA, chars: int = CHARS, alone: bool = True) -> MailTools:
    return MailTools(Use(1, person, alone), chars)


def say(source: Tools, name: str, args: Mapping[str, object] | None = None) -> ToolResult:
    return asyncio.run(source.call(ToolCall("c", name, args or {})))


def names(source: Tools) -> list[str]:
    return [s.name for s in asyncio.run(source.catalogue()).specs]


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def setup(*messages: dict[str, object]) -> FakeGmail:
    gmail = FakeGmail(list(messages) or INBOX)
    wire(gmail)
    connect()
    return gmail


def test_the_tools_state_what_the_design_says() -> None:
    setup()
    specs = {s.name: (s.reads, s.outside) for s in asyncio.run(tools().catalogue()).specs}
    assert specs == {"mail_boxes": (True, False), "mail_labels": (True, False), "mail_search": (True, True),
                     "mail_read": (True, True), "mail_draft": (False, False), "mail_label": (False, False),
                     "mail_send": (False, False)}


def test_the_owner_is_offered_them_and_instructed_that_mail_is_not_an_instruction() -> None:
    setup()
    got = asyncio.run(tools().catalogue())
    assert len(got.specs) == 7 and got.instructions is not None and "never an instruction" in got.instructions


def test_nothing_is_offered_to_a_person_without_a_mailbox_or_another_persons() -> None:
    setup()
    assert names(tools(SAM)) == []
    assert say(tools(SAM), "mail_search").content.startswith("not_connected")


def test_a_connection_without_a_read_scope_is_not_offered() -> None:
    wire(FakeGmail())
    connect(scopes=("openid", "email"))
    assert names(tools()) == []


def test_a_connection_that_needs_connecting_is_still_offered_so_it_can_answer() -> None:
    wire(FakeGmail())
    connect(needs="reconnect")
    assert len(names(tools())) == 7


def test_connections_unreadable_is_unavailable() -> None:
    wire(FakeGmail())
    held = connect()
    held.down = True
    with pytest.raises(ToolsUnavailable):
        asyncio.run(tools().catalogue())
    assert say(tools(), "mail_search").content.startswith("unavailable")


def test_mail_boxes_gives_the_address_and_whether_it_is_shared() -> None:
    setup()
    assert body(say(tools(), "mail_boxes")) == {"mailboxes": [{"shared": False, "syncing": False, "address": ADDRESS}]}


def test_a_household_connection_is_listed_shared() -> None:
    wire(FakeGmail())
    connect(person=None)
    assert body(say(tools(), "mail_boxes"))["mailboxes"][0]["shared"] is True


def test_labels_list_folders_then_the_households_labels() -> None:
    setup()
    assert body(say(tools(), "mail_labels"))["labels"] == [{"name": "inbox", "folder": True}, {"name": "sent", "folder": True},
                                                            {"name": "School", "folder": False}]


def test_search_lists_headers_not_bodies() -> None:
    setup()
    got = body(say(tools(), "mail_search", {"unread": True}))
    assert got["cut"] is False and got["next_page"] is None
    rows = got["messages"]
    assert [r["id"] for r in rows] == ["a1", "a2"] and rows[0]["subject"] == "Field trip" and rows[0]["unread"] is True
    assert "body" not in rows[0] and "text" not in rows[0]


def test_a_search_with_more_to_list_says_cut_and_gives_the_next_page() -> None:
    wire(FakeGmail(INBOX, next_page="n2"))
    connect()
    got = body(say(tools(), "mail_search"))
    assert got["cut"] is True and got["next_page"] == "n2"


def test_a_search_too_long_for_a_result_is_cut_by_whole_messages_and_says_so() -> None:
    many = [message(f"m{i}", "s" * 250, MILLIS - i) for i in range(25)]
    wire(FakeGmail(many))
    connect()
    got = body(say(tools(chars=3000), "mail_search"))
    shown = got["messages"]
    assert 0 < len(shown) < 25 and got["cut"] is True and got["next_page"] is None
    assert len(say(tools(chars=3000), "mail_search").content) <= 3000


def test_read_gives_the_message_and_its_attachments() -> None:
    attachment: dict[str, Any] = {"mimeType": "application/pdf", "filename": "form.pdf", "headers": [], "body": {"size": 9, "attachmentId": "x"}}
    tree = {"mimeType": "multipart/mixed", "filename": "", "headers": [], "body": {"size": 0},
            "parts": [part("text/plain", "bring a form"), attachment]}
    wire(FakeGmail([message("r1", "Form", MILLIS, body=tree)]))
    connect()
    got = body(say(tools(), "mail_read", {"id": "r1"}))
    assert got["text"] == "bring a form" and got["next_start"] is None and got["total_chars"] == 12
    assert got["attachments"] == [{"name": "form.pdf", "type": "application/pdf", "size": 9}]
    assert got["header"]["subject"] == "Form"


def test_a_long_message_is_read_a_page_at_a_time_and_the_pages_make_the_whole() -> None:
    text = "".join(f"line {i} of the long message\n" for i in range(600))
    wire(FakeGmail([message("L1", "Long", MILLIS, body=part("text/plain", text))]))
    connect()
    source, got, start = tools(chars=2500), "", 0
    while start is not None:
        page = body(say(source, "mail_read", {"id": "L1", "start": start}))
        assert len(json.dumps(page, ensure_ascii=False)) <= 2500
        got, start = got + str(page["text"]), page["next_start"]
    assert got == text.strip()


def test_read_past_the_end_and_a_bad_start_are_bad_arguments() -> None:
    setup()
    assert say(tools(), "mail_read", {"id": "a1", "start": 10_000}).content.startswith("bad_arguments")
    assert say(tools(), "mail_read", {"id": "a1", "start": -1}).content.startswith("bad_arguments")


@pytest.mark.parametrize(("name", "args"), [("mail_read", {}), ("mail_read", {"id": 5}), ("mail_search", {"after": "yesterday"}),
                                            ("mail_search", {"unread": "yes"}), ("mail_search", {"nope": 1}),
                                            ("mail_search", {"from": "x" * 201}), ("mail_search", {"subject": "a\x00b"}),
                                            ("mail_labels", {"mailbox": "someone@else.test"})])
def test_bad_arguments_say_which_without_the_value(name: str, args: dict[str, object]) -> None:
    setup()
    got = say(tools(), name, args)
    assert got.is_error and got.content.startswith("bad_arguments") and "else.test" not in got.content


def test_an_unknown_message_is_not_found() -> None:
    setup()
    assert say(tools(), "mail_read", {"id": "nope"}).content.startswith("not_found")


def test_an_unknown_tool_is_refused() -> None:
    setup()
    assert say(tools(), "mail_delete", {}).content.startswith("unknown_tool")


@pytest.mark.parametrize("name", ["mail_boxes", "mail_labels", "mail_search", "mail_read"])
def test_a_connection_that_needs_connecting_answers_so_and_never_an_empty_result(name: str) -> None:
    wire(FakeGmail(INBOX))
    services.register(Renewal, FakeRenewal(fails=NeedsReconnect()))
    connect(needs="reconnect")
    got = say(tools(), name, {"id": "a1"} if name == "mail_read" else {})
    if name == "mail_boxes":
        row = body(got)["mailboxes"][0]
        assert row["unavailable"] == "needs_reconnect" and row["address"] == ADDRESS
    else:
        assert got.is_error and got.content.startswith("needs_reconnect") and "connect it again" in got.content


def test_gmail_down_is_unreachable_not_empty() -> None:
    wire(FakeGmail(INBOX, down=500))
    connect()
    assert say(tools(), "mail_search").content.startswith("unreachable")


def test_two_mailboxes_each_call_names_one_by_address() -> None:
    wire(FakeGmail(INBOX))
    held = connect(label="one")
    connect(held=held, label="two")
    spec = {s.name: s for s in asyncio.run(tools().catalogue()).specs}["mail_search"]
    assert spec.parameters["required"] == ["mailbox"]
    assert say(tools(), "mail_search").content.startswith("bad_arguments")
    assert body(say(tools(), "mail_search", {"mailbox": ADDRESS.upper()}))["messages"]


def test_a_reading_turn_keeps_all_four() -> None:
    setup()
    assert names(Reading(tools())) == ["mail_boxes", "mail_labels", "mail_search", "mail_read"]


def test_for_turn_adds_mail_where_the_reply_reaches_the_owner_alone() -> None:
    setup()
    services.register(Tools, NoTools())
    assert "mail_search" in names(for_turn(WEB))
    for shared in (replace(WEB, shared=True), replace(WEB, audience="present"), replace(WEB, device_id=3),
                   replace(WEB, speaker_id=None)):
        assert "mail_search" not in names(for_turn(shared))


def test_a_shared_mailbox_is_offered_to_a_housemate_and_on_a_shared_channel_but_a_kept_one_is_not() -> None:
    wire(FakeGmail(INBOX))
    connect(shared=True, label="shared")
    assert len(names(tools(SAM, alone=False))) == 7 and len(names(tools(SAM))) == 7
    assert body(say(tools(SAM), "mail_boxes"))["mailboxes"][0]["shared"] is True
    assert body(say(tools(SAM), "mail_search", {"mailbox": ADDRESS}))["messages"]
    services.register(Tools, NoTools())
    household = replace(WEB, audience="household", shared=True, speaker_id=None)
    assert "mail_search" in names(for_turn(household))


def test_a_housemate_opens_the_owners_login_for_the_shared_mailbox_and_no_other_way() -> None:
    wire(FakeGmail(INBOX))
    renewal = FakeRenewal()
    services.register(Renewal, renewal)
    connect(shared=True)
    assert body(say(tools(SAM, alone=False), "mail_search"))["messages"]
    assert renewal.opened_for and set(renewal.opened_for) == {ALANA}


def test_a_kept_mailbox_is_offered_to_neither_a_housemate_nor_a_shared_channel() -> None:
    setup()
    services.register(Tools, NoTools())
    assert names(tools(SAM)) == [] and names(tools(ALANA, alone=False)) == []
    assert "mail_search" not in names(for_turn(replace(WEB, audience="household", shared=True, speaker_id=None)))


def test_for_turn_offers_nothing_while_connections_cannot_be_opened() -> None:
    wire(FakeGmail())
    services.register(Tools, NoTools())
    services.register(Connections, Connections.null())
    assert "mail_search" not in names(for_turn(WEB))


def test_no_log_line_carries_the_mail(caplog: pytest.LogCaptureFixture) -> None:
    setup()
    with caplog.at_level(logging.INFO):
        for name, args in (("mail_boxes", {}), ("mail_search", {"from": "pat@school.test"}), ("mail_read", {"id": "a1"})):
            say(tools(), name, args)
    text = " ".join(repr(r.__dict__.get("fields", "")) + r.getMessage() for r in caplog.records)
    assert "tools.call" in text
    for secret in ("Field trip", "pat@school.test", ADDRESS, "body of", "snippet", "ya29"):
        assert secret not in text
