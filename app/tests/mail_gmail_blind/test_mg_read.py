"""`mail_read` (design: tools table, "one message, paged with `start` and `next_start` as `git_read_file` is"; "Bodies are
turned to text in code, HTML included"; "`MailFailed` ... `not_found`"). Gmail's answers come from the fake."""

import re

import pytest
from ashley.channels.turn_tools import READABLE_CHARS
from mail_gmail_blind_support import (ADDRESS, READ, World, as_records, data, day, dig, failed, message, page_text)

PLAIN = "Café menu: soupe à l'oignon, 5 €.\nBring a spoon."
HTML = ("<html><head><style>p{color:red}</style></head><body><p>Dear <b>parents</b>,</p><p>Tom &amp; Jerry go on "
        "<a href='https://x.test/y'>Friday</a>.</p><script>alert('boo')</script></body></html>")
GMAIL_FIELDS = ("labelIds", "threadId", "internalDate", "payload", "mimeType", "partId", "sizeEstimate", "historyId")


def body_of(world: World, ident: str = "m1", **more: object) -> str:
    got = data(world.turn().call(READ, mailbox=ADDRESS, id=ident, **more))
    body = page_text(got)
    assert isinstance(body, str), got
    return body


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_a_plain_text_message_reads_as_its_text(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN))
    world.connect()
    assert body_of(world) == PLAIN


def test_the_message_carries_its_header_beside_the_body(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", sender="Alice Example <alice@school.test>", text=PLAIN,
                           labels=("INBOX", "UNREAD", "Label_12")))
    world.connect()
    got = data(world.turn().call(READ, mailbox=ADDRESS, id="m1"))
    assert dig(got, "id") == "m1" and dig(got, "subject") == "Menu"
    assert "alice@school.test" in str(dig(got, "from")) and str(dig(got, "date")).startswith("2026-03-04")
    assert "School" in dig(got, "labels")


def test_html_is_turned_to_text_in_code(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Letter", html=HTML))
    world.connect()
    text = squash(body_of(world))
    assert "Dear parents" in text and "Tom & Jerry" in text and "Friday" in text
    assert "<" not in text and ">" not in text and "&amp;" not in text
    assert "alert" not in text and "color:red" not in text


def test_a_message_with_both_parts_reads_as_its_plain_text(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Both", text="the plain one", html="<p>the html one</p>"))
    world.connect()
    assert squash(body_of(world)) == "the plain one"


def test_attachments_are_listed_by_name_type_and_size_and_never_fetched(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "With files", text="see attached",
                           attachments=(("menu.pdf", "application/pdf", 48213), ("pic.png", "image/png", 7))))
    world.connect()
    got = data(world.turn().call(READ, mailbox=ADDRESS, id="m1"))
    rows = as_records(dig(got, "attachments"))
    assert len(rows) == 2
    assert {(a["name"], a["type"], a["size"]) for a in rows} == {("menu.pdf", "application/pdf", 48213),
                                                                    ("pic.png", "image/png", 7)}
    assert body_of(world) == "see attached"
    assert not [s for s in world.fake.calls("gmail") if "attachments" in s.path]


def test_a_message_without_attachments_lists_none(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Bare", text="hi"))
    world.connect()
    assert dig(data(world.turn().call(READ, mailbox=ADDRESS, id="m1")), "attachments") in ([], 0)


def test_the_answer_is_the_neutral_record_not_gmails(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN, labels=("INBOX", "Label_12")))
    world.connect()
    text = world.turn().call(READ, mailbox=ADDRESS, id="m1").content
    assert not [f for f in GMAIL_FIELDS if f in text] and "Label_12" not in text


def test_an_unknown_message_is_not_found(world: World) -> None:
    world.connect()
    failed(world.turn().call(READ, mailbox=ADDRESS, id="nope"), "not_found")


def test_a_message_of_a_mailbox_the_person_does_not_hold_is_refused_before_gmail(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN))
    world.connect()
    assert world.turn().call(READ, mailbox="other@gmail.test", id="m1").is_error
    assert world.fake.calls("gmail") == []


def test_a_read_without_an_id_is_a_bad_call(world: World) -> None:
    world.connect()
    assert world.turn().call(READ, mailbox=ADDRESS).is_error


def test_gmail_down_is_unreachable_and_refusing_is_refused(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN))
    world.connect()
    world.fake.gmail_status, world.fake.gmail_code = 403, "PERMISSION_DENIED"
    failed(world.turn().call(READ, mailbox=ADDRESS, id="m1"), "refused")
    world.fake.gmail_status, world.fake.gmail_down = None, True
    failed(world.turn().call(READ, mailbox=ADDRESS, id="m1"), "unreachable")


def long_body() -> str:
    return "".join(f"line {i:05d} of the long letter\n" for i in range(max(READABLE_CHARS // 20, 200) * 6)) + "END"


def test_a_short_body_is_one_page_with_no_next_start(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN))
    world.connect()
    got = data(world.turn().call(READ, mailbox=ADDRESS, id="m1"))
    assert dig(got, "next_start") is None
    assert dig(got, "total_chars") == len(PLAIN)


def test_a_long_body_is_cut_to_a_page_that_fits_a_tool_result(world: World) -> None:
    text = long_body()
    world.fake.add(message("m1", day(3, 4), "Long", text=text))
    world.connect()
    got = data(world.turn().call(READ, mailbox=ADDRESS, id="m1"))
    first = page_text(got)
    assert 0 < len(first) <= READABLE_CHARS < len(text)
    assert dig(got, "total_chars") == len(text)
    assert isinstance(dig(got, "next_start"), int) and 0 < dig(got, "next_start") <= len(first)


def test_pages_read_from_next_start_reassemble_the_whole_body_exactly(world: World) -> None:
    text = long_body()
    world.fake.add(message("m1", day(3, 4), "Long", text=text))
    world.connect()
    turn, got, start, pages = world.turn(), "", 0, 0
    while start is not None and pages < 60:
        page = data(turn.call(READ, mailbox=ADDRESS, id="m1", start=start))
        chunk = page_text(page)
        assert 0 < len(chunk) <= READABLE_CHARS
        got += chunk
        nxt = dig(page, "next_start")
        assert nxt is None or nxt == len(got)
        start, pages = nxt, pages + 1
    assert start is None and got == text and pages > 1


def test_a_start_that_is_not_a_position_is_a_bad_call(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN))
    world.connect()
    for bad in (-1, "soon", 1.5):
        assert world.turn().call(READ, mailbox=ADDRESS, id="m1", start=bad).is_error


@pytest.mark.parametrize("secret", ["at-seed-0001-ACCESSTOKEN", "rt-seed-0001-REFRESHTOKEN", "gsecret-mail-CLIENTSECRET"])
def test_a_result_never_carries_a_credential(world: World, secret: str) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text=PLAIN))
    world.connect()
    turn = world.turn()
    seen = [turn.call(READ, mailbox=ADDRESS, id="m1").content, turn.call("mail_search", mailbox=ADDRESS).content,
            turn.call("mail_boxes").content, turn.call("mail_labels", mailbox=ADDRESS).content]
    assert not [c for c in seen if secret in c]
