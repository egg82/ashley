"""The IMAP adapter (`ashley.mail.imap.ImapMailbox`) reading from a fake Bridge on localhost sockets
(`mail_proton_support`): labels, search and read as neutral records, ids that are `Message-ID`s, the pinned certificate,
`syncing`, a signed-out account, and a `mail.call` line that carries ids and counts only."""

import asyncio
import logging
from collections.abc import Generator
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Any

import pytest
from ashley import services
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Header, Label, MailFailed, MailQuery, Message, Page
from mail_proton_support import ALANA, HOME, USER, Bridge, FakeBridge, mail, stocked, wire

ACCOUNT = Account(1, HOME, ALANA, "proton", USER)


@pytest.fixture(scope="module")
def fake() -> Generator[FakeBridge]:
    server = FakeBridge()
    yield server
    server.stop()


@pytest.fixture
def bridge(fake: FakeBridge) -> Bridge:
    state = stocked(fake)
    wire(fake)
    state.add("INBOX", mail("Field trip", message_id="<trip@school.test>"), ("\\Seen",), "07-Nov-2026 10:00:00 +0000")
    state.add("INBOX", mail("Receipt", sender="Shop <shop@store.test>", message_id="<rcpt@store.test>"), (),
              "06-Nov-2026 09:00:00 +0000")
    state.add("Sent", mail("Re: Lunch", sender=USER, to="sam@school.test", message_id="<lunch@proton.test>"), ("\\Seen",),
              "05-Nov-2026 08:00:00 +0000")
    state.add("Archive", mail("Old news", message_id="<old@school.test>"), ("\\Seen",), "01-Oct-2026 08:00:00 +0000")
    return state


def box() -> Mailbox:
    return services.get(Mailbox)


def search(query: MailQuery = MailQuery()) -> Page[Header]:
    return asyncio.run(box().search(ACCOUNT, query))


def failure(coro: Any) -> str:
    with pytest.raises(MailFailed) as e:
        asyncio.run(coro)
    return e.value.reason


def test_labels_are_the_folders_bridge_has_then_the_households_own_labels(bridge: Bridge) -> None:
    got = asyncio.run(box().labels(ACCOUNT))
    assert got == (Label("inbox", True), Label("archive", True), Label("sent", True), Label("drafts", True),
                   Label("spam", True), Label("trash", True), Label("School", False), Label("Café", False))


def test_a_search_with_no_folder_covers_inbox_archive_and_sent_newest_first_with_folder_and_unread(bridge: Bridge) -> None:
    page = search()
    assert [h.subject for h in page.items] == ["Field trip", "Receipt", "Re: Lunch", "Old news"]
    assert not page.cut and page.cursor == ""
    first, second, third, fourth = page.items
    assert (first.id, first.sender, first.to, first.folder, first.unread) == (
        "trip@school.test", "Sam <sam@school.test>", USER, "inbox", False)
    assert (second.unread, third.folder, fourth.folder) == (True, "sent", "archive")
    assert first.date == datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    assert first.snippet == "hello there"


def test_a_message_in_trash_or_spam_is_not_listed_unless_asked_for(bridge: Bridge) -> None:
    bridge.add("Trash", mail("Junk", message_id="<junk@x.test>"))
    assert "Junk" not in [h.subject for h in search().items]
    assert [h.subject for h in search(MailQuery(folder="trash")).items] == ["Junk"]


def test_a_search_gives_each_message_the_labels_whose_folder_holds_a_copy(bridge: Bridge) -> None:
    bridge.add("Labels/School", bridge.folders["INBOX"][0].raw, ("\\Seen",), "07-Nov-2026 10:00:00 +0000")
    by_subject = {h.subject: h.labels for h in search().items}
    assert by_subject["Field trip"] == ("School",) and by_subject["Receipt"] == ()


def test_the_query_narrows_by_sender_subject_text_unread_and_days(bridge: Bridge) -> None:
    assert [h.subject for h in search(MailQuery(sender="shop@store.test")).items] == ["Receipt"]
    assert [h.subject for h in search(MailQuery(subject="field trip")).items] == ["Field trip"]
    assert [h.subject for h in search(MailQuery(unread=True)).items] == ["Receipt"]
    assert [h.subject for h in search(MailQuery(after=date(2026, 11, 6))).items] == ["Field trip", "Receipt"]
    assert [h.subject for h in search(MailQuery(before=date(2026, 11, 1))).items] == ["Old news"]
    assert [h.subject for h in search(MailQuery(folder="sent")).items] == ["Re: Lunch"]
    assert search(MailQuery(text="no such words anywhere")).items == ()


def test_a_word_outside_ascii_is_searched_as_a_literal_and_intersected_with_the_rest(bridge: Bridge) -> None:
    bridge.add("INBOX", mail("Café menu", message_id="<cafe@x.test>"), (), "07-Nov-2026 11:00:00 +0000")
    bridge.add("INBOX", mail("Café closed", sender="Other <o@x.test>", message_id="<cafe2@x.test>"), (),
               "07-Nov-2026 11:30:00 +0000")
    assert [h.subject for h in search(MailQuery(subject="café")).items] == ["Café closed", "Café menu"]
    assert [h.subject for h in search(MailQuery(subject="café menu")).items] == ["Café menu"]


def test_search_syntax_in_a_value_is_words_and_never_a_criterion(bridge: Bridge) -> None:
    got = search(MailQuery(subject='trip") OR (ALL'))
    assert got.items == ()
    assert not any(c.startswith("UID SEARCH") and "OR" in c for c in bridge.commands)


def test_a_label_or_a_folder_that_is_a_label_lists_its_messages_with_the_folder_each_sits_in(bridge: Bridge) -> None:
    bridge.add("Labels/School", bridge.folders["INBOX"][0].raw, ("\\Seen",), "07-Nov-2026 10:00:00 +0000")
    for query in (MailQuery(label="school"), MailQuery(folder="School")):
        got = search(query).items
        assert [(h.subject, h.folder, h.labels) for h in got] == [("Field trip", "inbox", ("School",))]
    assert search(MailQuery(label="School", folder="archive")).items == ()
    assert search(MailQuery(label="Nothing")).items == ()


def test_has_attachment_filters_on_the_message_since_imap_cannot(bridge: Bridge) -> None:
    withfile = EmailMessage()
    withfile["From"], withfile["To"], withfile["Subject"], withfile["Message-ID"] = "a@x.test", USER, "Report", "<rep@x.test>"
    withfile["Date"] = "Sat, 07 Nov 2026 12:00:00 +0000"
    withfile.set_content("see attached")
    withfile.add_attachment(b"12345", maintype="application", subtype="pdf", filename="q3.pdf")
    bridge.add("INBOX", withfile.as_bytes(), (), "07-Nov-2026 12:00:00 +0000")
    got = search(MailQuery(has_attachment=True)).items
    assert [(h.subject, h.attachments) for h in got] == [("Report", 1)]
    assert "Report" not in [h.subject for h in search(MailQuery(has_attachment=False)).items]


def test_a_page_is_capped_by_the_settings_and_its_cursor_asks_for_the_rest(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake, search_max=3)
    first = search()
    assert [h.subject for h in first.items] == ["Field trip", "Receipt", "Re: Lunch"] and first.cut and first.cursor
    second = search(MailQuery(page=first.cursor))
    assert [h.subject for h in second.items] == ["Old news"] and not second.cut and second.cursor == ""
    assert failure(box().search(ACCOUNT, MailQuery(page="x'; DROP"))) == "refused"


def test_a_read_gives_the_body_as_text_and_the_message_by_its_message_id(bridge: Bridge) -> None:
    got = asyncio.run(box().read(ACCOUNT, "rcpt@store.test"))
    assert got.header.subject == "Receipt" and got.header.unread and got.header.folder == "inbox"
    assert got.body == "hello there" and not got.body_cut and got.attachments == ()


def test_a_read_turns_an_html_only_message_to_text_and_lists_attachments(bridge: Bridge) -> None:
    html = EmailMessage()
    html["From"], html["To"], html["Subject"], html["Message-ID"] = "a@x.test", USER, "Page", "<html@x.test>"
    html["Date"] = "Sat, 07 Nov 2026 12:00:00 +0000"
    html.set_content("<p>Hello <b>there</b></p><script>bad()</script>", subtype="html")
    html.add_attachment(b"abcdef", maintype="image", subtype="png", filename="pic.png")
    bridge.add("INBOX", html.as_bytes())
    got = asyncio.run(box().read(ACCOUNT, "html@x.test"))
    assert got.body == "Hello there" and [(a.name, a.media_type, a.size) for a in got.attachments] == [("pic.png", "image/png", 6)]


def test_a_message_with_no_message_id_is_named_by_a_hash_and_found_again(bridge: Bridge) -> None:
    bridge.add("Archive", mail("No id", message_id=None), (), "02-Oct-2026 08:00:00 +0000")
    listed = [h for h in search().items if h.subject == "No id"]
    assert len(listed) == 1 and listed[0].id.startswith("nomid-") and len(listed[0].id) == 38
    assert asyncio.run(box().read(ACCOUNT, listed[0].id)).header.subject == "No id"
    assert failure(box().read(ACCOUNT, "nomid-" + "0" * 32)) == "not_found"


def test_an_id_longer_than_the_settings_allow_is_cut_and_still_finds_its_message(bridge: Bridge, fake: FakeBridge) -> None:
    config = wire(fake)
    long = "x" * 80 + "@long.test"
    bridge.add("INBOX", mail("Long id", message_id=f"<{long}>"), (), "07-Nov-2026 13:00:00 +0000")
    listed = next(h for h in search().items if h.subject == "Long id")
    assert listed.id == long[:config.message_id_chars]
    assert asyncio.run(box().read(ACCOUNT, listed.id)).header.subject == "Long id"


def test_the_id_survives_a_resync_that_gives_every_message_a_new_uid(bridge: Bridge) -> None:
    before = {h.subject: h.id for h in search().items}
    for stored in bridge.folders["INBOX"]:
        stored.uid += 1000
    assert {h.subject: h.id for h in search().items} == before
    assert asyncio.run(box().read(ACCOUNT, before["Receipt"])).header.subject == "Receipt"


def test_an_id_that_is_none_of_this_mailboxs_or_cannot_be_one_is_not_found(bridge: Bridge) -> None:
    for ident in ("nothing@here.test", "", "a b", "x" * 65, 'q"uote', "back\\slash"):
        assert failure(box().read(ACCOUNT, ident)) == "not_found"


def test_the_uid_may_come_last_in_a_fetch_answer(bridge: Bridge) -> None:
    bridge.uid_last = True
    assert [h.subject for h in search().items][0] == "Field trip"


def test_a_mailbox_not_yet_synced_in_this_epoch_answers_syncing_and_asks_bridge_for_nothing(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake, synced=False)
    for call in (box().labels(ACCOUNT), box().search(ACCOUNT, MailQuery()), box().read(ACCOUNT, "trip@school.test")):
        assert failure(call) == "syncing"
    assert bridge.logins == 0 and asyncio.run(box().still_syncing(ACCOUNT))


def test_a_synced_mailbox_is_not_syncing(bridge: Bridge) -> None:
    assert not asyncio.run(box().still_syncing(ACCOUNT))


def test_an_account_bridge_signed_out_needs_reconnect(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake, state="signed_out")
    assert failure(box().search(ACCOUNT, MailQuery())) == "needs_reconnect" and bridge.logins == 0


def test_a_password_bridge_refuses_needs_reconnect(bridge: Bridge) -> None:
    bridge.password = "rotated"
    assert failure(box().search(ACCOUNT, MailQuery())) == "needs_reconnect"


def test_a_certificate_that_is_not_the_pods_is_unreachable_and_no_login_is_sent(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake, certificate="0" * 64)
    assert failure(box().search(ACCOUNT, MailQuery())) == "unreachable" and bridge.logins == 0
    wire(fake, certificate=None)
    assert failure(box().search(ACCOUNT, MailQuery())) == "unreachable" and bridge.logins == 0


def test_no_bridge_listening_is_unreachable(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake)
    fake.imap_port, port = 1, fake.imap_port
    try:
        wire(fake)
        assert failure(box().search(ACCOUNT, MailQuery())) == "unreachable"
    finally:
        fake.imap_port = port


def test_an_address_the_account_does_not_hold_is_not_found_and_no_login_is_sent(bridge: Bridge) -> None:
    other = Account(1, HOME, ALANA, "proton", "someone@else.test")
    assert failure(box().search(other, MailQuery())) == "not_found" and bridge.logins == 0


def test_a_call_logs_ids_counts_and_a_duration_and_nothing_a_person_wrote(bridge: Bridge, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="ashley.mail"):
        search(MailQuery(subject="field trip"))
    lines = [r.__dict__["fields"] for r in caplog.records if r.name == "ashley.mail"]
    assert len(lines) == 1
    assert {k: v for k, v in lines[0].items() if k != "duration_ms"} == {"connection": 1, "call": "search", "status": "ok",
                                                                         "count": 1}
    assert isinstance(lines[0]["duration_ms"], int)
    text = repr(lines) + " ".join(r.getMessage() for r in caplog.records)
    for secret in (USER, "field trip", "Field", "school.test", "bridge-issued-password"):
        assert secret not in text


def test_a_message_read_back_has_the_header_a_person_sees(bridge: Bridge) -> None:
    got: Message = asyncio.run(box().read(ACCOUNT, "trip@school.test"))
    assert (got.header.sender, got.header.to, got.header.subject, got.header.unread) == (
        "Sam <sam@school.test>", USER, "Field trip", False)
