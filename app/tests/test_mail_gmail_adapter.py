"""The Gmail adapter (`ashley.mail.gmail.GmailMailbox`) over a fake Gmail at its HTTP boundary: the profile, labels,
a search and a read as neutral records; the access token Renewal gives sent as a bearer; what Gmail or Renewal
refuses comes back as a `MailFailed` reason; and `mail.call` carries ids and counts, never a subject, address or
token."""

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest
from ashley import services
from ashley.connections.connections import ConnectionsUnavailable
from ashley.connections.oauth import OAuthUnavailable
from ashley.connections.renewal import NeedsReconnect, Renewal
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Header, Label, MailFailed, MailQuery, Message, Page
from mail_gmail_support import ADDRESS, ALANA, HOME, TOKEN, FakeGmail, FakeRenewal, b64, message, part, wire

ACCOUNT = Account(1, HOME, ALANA)
MILLIS = 1_762_000_000_000
INBOX = [message("a1", "Field trip", MILLIS, ("INBOX", "UNREAD", "Label_7", "CATEGORY_UPDATES")),
         message("a2", "Receipt", MILLIS - 5000, ("SENT",)), message("a3", "Old", MILLIS - 9000, ())]


def box(gmail: FakeGmail) -> Mailbox:
    wire(gmail)
    return services.get(Mailbox)


def search(mailbox: Mailbox, query: MailQuery) -> Page[Header]:
    return asyncio.run(mailbox.search(ACCOUNT, query))


def read(mailbox: Mailbox, message_id: str) -> Message:
    return asyncio.run(mailbox.read(ACCOUNT, message_id))


def failure(coro: Any) -> str:
    with pytest.raises(MailFailed) as e:
        asyncio.run(coro)
    return e.value.reason


def test_the_address_is_the_profiles_and_the_token_is_sent_as_a_bearer() -> None:
    gmail = FakeGmail(INBOX)
    assert asyncio.run(box(gmail).address(ACCOUNT)) == ADDRESS
    assert gmail.seen[0][2] == f"Bearer {TOKEN}"
    renewal = services.get(Renewal)
    assert isinstance(renewal, FakeRenewal) and renewal.asked == [1]


def test_labels_are_the_folders_then_the_households_own_labels() -> None:
    found = asyncio.run(box(FakeGmail()).labels(ACCOUNT))
    assert found == (Label("inbox", True), Label("sent", True), Label("School", False))


def test_a_search_gives_headers_newest_first_with_folder_labels_and_unread() -> None:
    gmail = FakeGmail(INBOX)
    page = search(box(gmail), MailQuery())
    assert [h.id for h in page.items] == ["a1", "a2", "a3"] and not page.cut and page.cursor == ""
    first, second, third = page.items
    assert (first.sender, first.to, first.subject) == ("Pat <pat@school.test>", ADDRESS, "Field trip")
    assert first.date == datetime.fromtimestamp(MILLIS / 1000, UTC)
    assert (first.folder, first.labels, first.unread, first.snippet) == ("inbox", ("School",), True, "snippet Field trip")
    assert (second.folder, second.unread, second.labels) == ("sent", False, ())
    assert third.folder == ""


def test_a_search_reads_each_listed_message_in_full_since_metadata_omits_the_parts_that_count_attachments() -> None:
    gmail = FakeGmail(INBOX)
    search(box(gmail), MailQuery())
    full = [q for p, q, _ in gmail.seen if p == "/messages/a1"]
    assert full == [{"format": ["full"]}]


def test_the_query_becomes_gmails_search_and_the_page_is_capped_by_the_settings() -> None:
    gmail = FakeGmail(INBOX)
    config = wire(gmail)
    query = MailQuery(sender="pat@school.test", subject="field trip", after=date(2026, 10, 1), folder="inbox",
                      unread=True, has_attachment=True, page="tok")
    search(services.get(Mailbox), query)
    listed = next(q for p, q, _ in gmail.seen if p == "/messages")
    assert listed["q"] == ["from:(pat@school.test) subject:(field trip) after:2026/10/01 in:inbox is:unread has:attachment"]
    assert listed["maxResults"] == [str(config.search_max)] and listed["pageToken"] == ["tok"]


def test_more_than_was_listed_is_marked_cut_with_the_cursor_to_ask_for_it() -> None:
    page = search(box(FakeGmail(INBOX, next_page="next-1")), MailQuery())
    assert page.cut and page.cursor == "next-1"


def test_a_message_deleted_between_the_list_and_the_read_is_left_out() -> None:
    page = search(box(FakeGmail(INBOX, gone={"a2"})), MailQuery())
    assert [h.id for h in page.items] == ["a1", "a3"]


def test_a_plain_message_reads_with_its_body_and_no_cut() -> None:
    got = read(box(FakeGmail(INBOX)), "a1")
    assert got.header.id == "a1" and got.body == "body of Field trip" and not got.body_cut and got.attachments == ()


def test_html_only_mail_is_turned_to_text() -> None:
    html = "<html><head><style>p{}</style></head><body><p>Hello&nbsp;<b>Sam</b></p><script>x()</script><div>Bring lunch</div></body></html>"
    body = part("text/html", html)
    got = read(box(FakeGmail([message("h1", "Html", MILLIS, body=body)])), "h1")
    assert got.body == "Hello Sam\n\nBring lunch"


def test_the_plain_part_of_an_alternative_wins_and_attachments_are_listed() -> None:
    attachment: dict[str, Any] = {"mimeType": "application/pdf", "filename": "form.pdf", "headers": [],
                  "body": {"size": 2048, "attachmentId": "att1"}}
    tree = {"mimeType": "multipart/mixed", "filename": "", "headers": [], "body": {"size": 0}, "parts": [
        {"mimeType": "multipart/alternative", "filename": "", "headers": [], "body": {"size": 0},
         "parts": [part("text/plain", "plain words"), part("text/html", "<p>html words</p>")]}, attachment]}
    got = read(box(FakeGmail([message("m1", "Mixed", MILLIS, body=tree)])), "m1")
    assert got.body == "plain words"
    assert [(a.name, a.media_type, a.size) for a in got.attachments] == [("form.pdf", "application/pdf", 2048)]


def test_a_part_is_decoded_in_its_own_charset() -> None:
    body = part("text/plain", "café", charset="iso-8859-1")
    assert b64("café", "iso-8859-1") == body["body"]["data"]
    assert read(box(FakeGmail([message("c1", "Cafe", MILLIS, body=body)])), "c1").body == "café"


def test_a_body_over_the_settings_is_cut_and_says_so() -> None:
    wire(FakeGmail([message("b1", "Big", MILLIS, body=part("text/plain", "x" * 5000))]), body_chars=100)
    got = read(services.get(Mailbox), "b1")
    assert len(got.body) == 100 and got.body_cut


@pytest.mark.parametrize("bad", ["", "../labels", "a1/../../x", "x" * 65, "a b"])
def test_an_id_that_is_not_a_message_id_is_not_found_and_never_sent(bad: str) -> None:
    gmail = FakeGmail(INBOX)
    assert failure(box(gmail).read(ACCOUNT, bad)) == "not_found"
    assert gmail.seen == []


def test_an_unknown_message_is_not_found() -> None:
    assert failure(box(FakeGmail(INBOX)).read(ACCOUNT, "zzz")) == "not_found"


@pytest.mark.parametrize(("status", "reason"), [(401, "refused"), (403, "refused"), (404, "not_found"), (400, "not_found"),
                                                (429, "unreachable"), (500, "unreachable"), (503, "unreachable")])
def test_what_gmail_answers_is_a_reason(status: int, reason: str) -> None:
    assert failure(box(FakeGmail(INBOX, down=status)).search(ACCOUNT, MailQuery())) == reason


def test_an_answer_that_is_not_gmails_is_unreachable() -> None:
    assert failure(box(FakeGmail(INBOX, garbage=True)).address(ACCOUNT)) == "unreachable"


@pytest.mark.parametrize(("fails", "reason"), [(NeedsReconnect(), "needs_reconnect"), (OAuthUnavailable("x"), "unreachable"),
                                               (ConnectionsUnavailable("x"), "unreachable")])
def test_renewal_failing_is_a_reason_and_gmail_is_never_called(fails: Exception, reason: str) -> None:
    gmail = FakeGmail(INBOX)
    wire(gmail)
    services.register(Renewal, FakeRenewal(fails=fails))
    assert failure(services.get(Mailbox).search(ACCOUNT, MailQuery())) == reason
    assert gmail.seen == []


def test_no_such_connection_is_refused() -> None:
    class Nobody(FakeRenewal):
        async def access_token(self, connection_id: int, household_id: int, person_id: int | None = None) -> str | None:
            return None

    wire(FakeGmail())
    services.register(Renewal, Nobody())
    assert failure(services.get(Mailbox).address(ACCOUNT)) == "refused"


def test_scopes_that_read_are_gmails_readonly_and_modify_and_the_whole_mailbox() -> None:
    adapter = box(FakeGmail())

    def can(scopes: tuple[str, ...]) -> bool:
        return adapter.can_read("google", scopes)
    assert can(("openid", "https://www.googleapis.com/auth/gmail.readonly"))
    assert can(("https://www.googleapis.com/auth/gmail.modify",)) and can(("https://mail.google.com/",))
    assert not can(("openid", "email")) and not can(())


def test_the_log_line_has_ids_and_counts_and_none_of_the_mail(caplog: pytest.LogCaptureFixture) -> None:
    gmail = FakeGmail(INBOX)
    with caplog.at_level(logging.INFO, logger="ashley.mail"):
        search(box(gmail), MailQuery(sender="pat@school.test"))
        failure(box(FakeGmail(INBOX, down=500)).read(ACCOUNT, "a1"))
    lines = [r.__dict__["fields"] for r in caplog.records if r.name == "ashley.mail"]
    assert len(lines) == 2
    assert (lines[0]["call"], lines[0]["count"], lines[0]["status"], lines[0]["connection"]) == ("search", 3, "ok", 1)
    assert (lines[1]["call"], lines[1]["status"]) == ("read", "unreachable")
    text = repr(lines) + " ".join(r.getMessage() for r in caplog.records)
    for secret in (TOKEN, "Field trip", "pat@school.test", ADDRESS, "snippet"):
        assert secret not in text
