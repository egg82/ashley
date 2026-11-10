"""`mail_search` (design: tools table; "headers matching a `MailQuery`, newest first, capped and marked `cut`"; "the
adapters ... each is the only code that reads its provider's field names"). Gmail's answers come from the fake at its
HTTP boundary, in the shapes of Gmail's reference."""

from datetime import timedelta
from typing import Any

import pytest
from mail_gmail_blind_fake_support import encoded
from mail_gmail_blind_support import (ABSENT, ADDRESS, SEARCH, World, attachment_count, data, day, dig, failed, headers_of,
                                      ids_of, message, search)

GMAIL_FIELDS = ("labelIds", "threadId", "internalDate", "resultSizeEstimate", "nextPageToken", "sizeEstimate", "historyId",
                "payload", "metadataHeaders")


def stock(world: World) -> None:
    world.fake.add(
        message("m1", day(3, 1), "Trip money", labels=("INBOX", "UNREAD", "Label_12"), text="bring ten dollars"),
        message("m2", day(3, 5), "Lunch menu", sender="Bob <bob@cafe.test>", text="soup on monday",
                attachments=(("menu.pdf", "application/pdf", 99),)),
        message("m3", day(3, 3), "Old news", labels=("Label_13",), text="nothing new"),
        message("m4", day(3, 9), "Junk offer", labels=("SPAM",), text="win money"),
        message("m5", day(3, 7), "Sent note", sender="Alana <alana@gmail.test>", labels=("SENT",), to="alice@school.test",
                text="thanks"))
    world.connect()


def found(world: World, **query: object) -> list[str]:
    return ids_of(search(world.turn(), **query))


def test_a_header_is_the_neutral_record_with_each_field_read_from_gmails(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Field trip", sender="Alice Example <alice@school.test>", snippet="Please bring",
                           labels=("INBOX", "UNREAD", "Label_12"), text="body",
                           attachments=(("a.pdf", "application/pdf", 10), ("b.png", "image/png", 20))))
    world.connect()
    [h] = headers_of(search(world.turn()))
    assert h["id"] == "m1"
    assert "alice@school.test" in h["from"] and ADDRESS in str(h["to"])
    assert h["subject"] == "Field trip" and h["snippet"] == "Please bring"
    assert str(h["date"]).startswith("2026-03-04")
    assert "School" in h["labels"] and h["unread"] is True and str(h["folder"]).lower() == "inbox"
    assert attachment_count(h) == 2


def test_a_read_message_without_attachments_is_not_unread_and_has_none(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Plain", labels=("INBOX",), text="body"))
    world.connect()
    [h] = headers_of(search(world.turn()))
    assert h["unread"] is False and attachment_count(h) == 0


def test_the_answer_carries_no_gmail_field_name_and_no_label_id(world: World) -> None:
    stock(world)
    text = world.turn().call(SEARCH, mailbox=ADDRESS).content
    assert not [f for f in GMAIL_FIELDS if f in text], text
    assert "Label_12" not in text and "UNREAD" not in text


def test_an_encoded_word_subject_is_decoded(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Café menu", subject_header=encoded("Café menu"), text="x"))
    world.connect()
    assert [h["subject"] for h in headers_of(search(world.turn()))] == ["Café menu"]


def test_newest_first_whatever_order_gmail_stored(world: World) -> None:
    stock(world)
    assert found(world) == ["m5", "m2", "m3", "m1"]


def test_spam_and_trash_are_not_shown_as_mail(world: World) -> None:
    stock(world)
    assert "m4" not in found(world)


@pytest.mark.parametrize(("query", "expected"), [
    ({"from": "bob@cafe.test"}, ["m2"]),
    ({"from": "alice"}, ["m3", "m1"]),
    ({"to": "alice@school.test"}, ["m5"]),
    ({"subject": "lunch menu"}, ["m2"]),
    ({"text": "ten dollars"}, ["m1"]),
    ({"after": "2026-03-04"}, ["m5", "m2"]),
    ({"before": "2026-03-04"}, ["m3", "m1"]),
    ({"after": "2026-03-02", "before": "2026-03-06"}, ["m2", "m3"]),
    ({"unread": True}, ["m1"]),
    ({"has_attachment": True}, ["m2"]),
    ({"label": "School"}, ["m1"]),
    ({"folder": "INBOX"}, ["m2", "m1"]),
    ({"from": "alice", "unread": True}, ["m1"]),
    ({"from": "bob", "unread": True}, []),
], ids=["from-address", "from-name", "to", "subject", "text", "after", "before", "window", "unread", "attachment", "label",
        "folder", "two-filters", "no-match"])
def test_each_query_field_selects_what_gmail_says_it_does(world: World, query: dict[str, Any], expected: list[str]) -> None:
    stock(world)
    assert found(world, **query) == expected


def test_nothing_found_is_an_answer_with_no_headers_not_cut_and_not_an_error(world: World) -> None:
    stock(world)
    got = data(world.turn().call(SEARCH, mailbox=ADDRESS, subject="zebra"))
    assert headers_of(got) == [] and dig(got, "cut") is False


def test_a_search_that_fits_is_not_cut(world: World) -> None:
    stock(world)
    got = search(world.turn())
    assert dig(got, "cut") is False
    assert dig(got, "next_page") in (None, ABSENT)


def many(world: World, n: int) -> list[str]:
    start = day(1, 1, 0)
    world.fake.add(*(message(f"x{i:04d}", start + timedelta(hours=i), f"Note {i}", text=f"t{i}") for i in range(n)))
    world.connect()
    return [f"x{i:04d}" for i in reversed(range(n))]


def test_a_search_with_more_matches_than_the_cap_answers_the_newest_and_says_cut(world: World) -> None:
    newest_first = many(world, 260)
    got = search(world.turn())
    shown = ids_of(got)
    assert 0 < len(shown) < 260
    assert shown == newest_first[:len(shown)]
    assert dig(got, "cut") is True
    assert dig(got, "next_page") not in (None, ABSENT)


def test_paging_to_the_end_gives_every_match_once_in_order_and_the_last_page_is_not_cut(world: World) -> None:
    newest_first = many(world, 260)
    turn, page, last = world.turn(), None, {}
    seen: list[str] = []
    for _ in range(80):
        last = search(turn, **({} if page is None else {"page": page}))
        seen += ids_of(last)
        page = dig(last, "next_page")
        if page in (None, ABSENT):
            break
        assert dig(last, "cut") is True
    assert seen == newest_first
    assert dig(last, "cut") is False


def test_a_page_size_larger_than_gmail_allows_is_never_asked_for(world: World) -> None:
    many(world, 30)
    search(world.turn())
    sizes = [int(s.one("maxResults") or 0) for s in world.fake.calls("gmail") if s.path == "/messages"]
    assert sizes and all(0 < n <= 500 for n in sizes)


def test_a_search_never_fetches_more_headers_than_it_shows(world: World) -> None:
    many(world, 260)
    shown = len(ids_of(search(world.turn())))
    gets = [s for s in world.fake.calls("gmail") if s.path.startswith("/messages/")]
    assert len(gets) <= shown


def test_a_date_that_is_not_a_date_is_a_bad_call_and_reaches_no_gmail(world: World) -> None:
    stock(world)
    seen = len(world.fake.seen)
    assert world.turn().call(SEARCH, mailbox=ADDRESS, after="last tuesday").is_error
    assert len(world.fake.seen) == seen


def test_an_argument_the_tool_does_not_have_is_refused(world: World) -> None:
    stock(world)
    assert world.turn().call(SEARCH, mailbox=ADDRESS, delete_everything=True).is_error


def test_gmail_refusing_unreachable_and_down_are_told_apart(world: World) -> None:
    stock(world)
    world.fake.gmail_status, world.fake.gmail_code = 403, "PERMISSION_DENIED"
    failed(world.turn().call(SEARCH, mailbox=ADDRESS), "refused")
    world.fake.gmail_status, world.fake.gmail_code = 503, "UNAVAILABLE"
    failed(world.turn().call(SEARCH, mailbox=ADDRESS), "unreachable")
    world.fake.gmail_status, world.fake.gmail_down = None, True
    failed(world.turn().call(SEARCH, mailbox=ADDRESS), "unreachable")
