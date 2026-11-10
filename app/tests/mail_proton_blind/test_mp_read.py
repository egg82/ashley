"""Proton's mailbox through the same read tools as Gmail (design: "`ImapMailbox` read calls behind the same tools"; the
neutral records of `ashley.mail.model`): the mailboxes, the folders and labels, a search over what Bridge holds, one message
read."""

from datetime import datetime
from typing import Any

from mail_proton_blind_store_support import compose, when
from mail_proton_blind_support import (ALANA_ADDRESS, BOXES, CONFIG, LABELS, M1, M2, M3, M4, M5, M6, READ, ROW_KEYS, SEARCH,
                                       SUBJECTS, Box, World, data, failed, rows, stock)

SUBJECT_OF = {v: k for k, v in SUBJECTS.items()}


def subjects(world: World, **query: object) -> list[str]:
    return [r["subject"] for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, **query))]


def test_the_mailbox_is_listed_by_address_as_kept_and_synced(world: World, alana: Box) -> None:
    (row,) = data(world.turn().call(BOXES))["mailboxes"]
    assert row["address"] == ALANA_ADDRESS and row["shared"] is False and row["syncing"] is False


def test_folders_come_first_in_lower_case_then_the_households_labels(world: World, alana: Box) -> None:
    stock(alana)
    got = data(world.turn().call(LABELS, mailbox=ALANA_ADDRESS))["labels"]
    folders = [l["name"] for l in got if l["folder"]]
    labels = [l["name"] for l in got if not l["folder"]]
    assert {"inbox", "sent", "drafts"} <= set(folders) and all(f == f.lower() for f in folders)
    assert sorted(labels) == ["Receipts", "School"]
    assert [l["folder"] for l in got] == sorted((l["folder"] for l in got), reverse=True)
    assert not [l["name"] for l in got if "/" in l["name"] or l["name"].lower() in ("all mail", "labels", "folders")]
    assert all(set(l) == {"name", "folder"} for l in got)


def test_an_inbox_search_lists_the_inbox_newest_first_as_neutral_records(world: World, alana: Box) -> None:
    stock(alana)
    got = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox"))
    assert [r["subject"] for r in got] == [SUBJECTS[M1], SUBJECTS[M2], SUBJECTS[M3]]
    for r in got:
        assert set(r) == ROW_KEYS and r["folder"] == "inbox"
        assert datetime.fromisoformat(r["date"]).tzinfo is not None
    first, second, third = got
    assert "pat@school.test" in first["from"] and "Pat" in first["from"] and ALANA_ADDRESS in first["to"]
    assert first["labels"] == ["School"] and first["unread"] is True and first["attachments"] == 0
    assert second["unread"] is False and second["labels"] == [] and second["attachments"] == 1
    assert "ten dollars" in first["snippet"] and "<" not in third["snippet"] and "today" in third["snippet"]


def test_the_date_is_the_messages_own_day(world: World, alana: Box) -> None:
    stock(alana)
    got = {r["subject"]: datetime.fromisoformat(r["date"]) for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))}
    assert (got[SUBJECTS[M1]].month, got[SUBJECTS[M1]].day) == (3, 4)
    assert (got[SUBJECTS[M6]].month, got[SUBJECTS[M6]].day) == (2, 20)


def test_a_search_without_a_folder_lists_each_message_once_and_not_spam_or_trash(world: World, alana: Box) -> None:
    stock(alana)
    alana.account.seed("Trash", compose("Binned", "x@y.test", ALANA_ADDRESS, when(3, 7), "bye", message_id="<t1@y.test>"))
    assert subjects(world) == [SUBJECTS[M4], SUBJECTS[M1], SUBJECTS[M2], SUBJECTS[M3], SUBJECTS[M6]]


def test_a_search_without_a_folder_is_newest_first_across_folders(world: World, alana: Box) -> None:
    stock(alana)
    got = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    stamps = [datetime.fromisoformat(r["date"]) for r in got]
    assert stamps == sorted(stamps, reverse=True) and len(got) == 5


def test_spam_sent_and_archive_are_folders_of_their_own(world: World, alana: Box) -> None:
    stock(alana)
    assert subjects(world, folder="spam") == [SUBJECTS[M5]]
    assert subjects(world, folder="sent") == [SUBJECTS[M4]]
    (archived,) = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="archive"))
    assert archived["subject"] == SUBJECTS[M6] and archived["labels"] == ["Receipts"] and archived["folder"] == "archive"


def test_a_labelled_message_is_one_message_in_its_folder_and_in_its_label(world: World, alana: Box) -> None:
    stock(alana)
    by_label = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, label="School"))
    inbox = {r["subject"]: r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox"))}
    assert [r["subject"] for r in by_label] == [SUBJECTS[M1]]
    assert by_label[0]["id"] == inbox[SUBJECTS[M1]]["id"] and by_label[0]["folder"] == "inbox"


def test_each_filter_narrows_the_search(world: World, alana: Box) -> None:
    stock(alana)
    assert subjects(world, **{"from": "bob@shop"}) == [SUBJECTS[M2], SUBJECTS[M6]]
    assert subjects(world, to="pat@school.test") == [SUBJECTS[M4]]
    assert subjects(world, subject="invoice") == [SUBJECTS[M2]]
    assert subjects(world, text="lamp") == [SUBJECTS[M6]]
    assert subjects(world, after="2026-03-03", before="2026-03-05") == [SUBJECTS[M1], SUBJECTS[M2]]
    assert subjects(world, unread=True, folder="inbox") == [SUBJECTS[M1]]
    assert subjects(world, unread=False, folder="inbox") == [SUBJECTS[M2], SUBJECTS[M3]]
    assert subjects(world, has_attachment=True) == [SUBJECTS[M2]]
    assert subjects(world, label="Receipts") == [SUBJECTS[M6]]
    assert subjects(world, folder="inbox", **{"from": "bob"}, text="friday") == [SUBJECTS[M2]]
    assert subjects(world, text="no such words anywhere") == []


def test_a_search_cut_at_the_cap_pages_with_the_cursor_and_loses_nothing(world: World, alana: Box) -> None:
    for n in range(CONFIG.search_max + 6):
        sent = when(4, 1 + n // 24, n % 24)
        alana.account.seed("INBOX", compose(f"Bulk {n:03d}", "Pat <pat@school.test>", ALANA_ADDRESS, sent, f"body {n}",
                                           message_id=f"<bulk{n}@school.test>"), when=sent)
    first = data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox"))
    assert len(first["messages"]) == CONFIG.search_max and first["cut"] is True and first["next_page"]
    second = data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox", page=first["next_page"]))
    ids = [m["id"] for m in first["messages"] + second["messages"]]
    assert len(ids) == len(set(ids)) == CONFIG.search_max + 6 and second["cut"] is False and not second["next_page"]
    stamps = [datetime.fromisoformat(m["date"]) for m in first["messages"] + second["messages"]]
    assert stamps == sorted(stamps, reverse=True)


def test_a_search_with_no_match_in_a_synced_mailbox_is_an_empty_list_not_an_error(world: World, alana: Box) -> None:
    got = data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    assert got["messages"] == [] and got["cut"] is False


def read(world: World, ident: str, **extra: object) -> dict[str, Any]:
    return data(world.turn().call(READ, mailbox=ALANA_ADDRESS, id=ident, **extra))


def listed(world: World, subject: str) -> dict[str, Any]:
    return next(r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)) if r["subject"] == subject)


def test_a_read_gives_the_text_the_header_and_the_attachments(world: World, alana: Box) -> None:
    stock(alana)
    got = read(world, listed(world, SUBJECTS[M2])["id"])
    assert got["text"].strip() == "Pay by Friday" and got["total_chars"] == len(got["text"]) and got["next_start"] is None
    assert got["header"]["subject"] == SUBJECTS[M2] and set(got["header"]) == ROW_KEYS
    assert got["attachments"] == [{"name": "invoice.pdf", "type": "application/pdf", "size": got["attachments"][0]["size"]}]
    assert got["attachments"][0]["size"] > 0 and got["truncated"] is False and got["start"] == 0


def test_html_only_mail_is_read_as_text_without_tags_or_scripts(world: World, alana: Box) -> None:
    stock(alana)
    text = read(world, listed(world, SUBJECTS[M3])["id"])["text"]
    assert "Soup" in text and "today" in text and "<" not in text and "x()" not in text


def test_the_plain_part_is_read_when_there_is_also_an_html_one(world: World, alana: Box) -> None:
    alana.account.seed("INBOX", compose("Both", "a@b.test", ALANA_ADDRESS, when(3, 1), "plain words here", message_id="<b@x.test>",
                                       html="<p>html words there</p>"))
    text = read(world, listed(world, "Both")["id"])["text"]
    assert "plain words here" in text and "html words" not in text


def test_other_charsets_and_encoded_headers_are_decoded(world: World, alana: Box) -> None:
    alana.account.seed("INBOX", compose("=?utf-8?b?Q2Fmw6kgcGxhbnM=?=", "=?utf-8?q?Zo=C3=AB?= <zoe@x.test>", ALANA_ADDRESS,
                                       when(3, 2), "café crème", charset="iso-8859-1", cte="quoted-printable",
                                       message_id="<c@x.test>"))
    (row,) = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    assert row["subject"] == "Café plans" and "Zoë" in row["from"]
    assert read(world, row["id"])["text"].strip() == "café crème"


def test_a_body_longer_than_the_cap_is_cut_and_says_so(world: World, alana: Box) -> None:
    alana.account.seed("INBOX", compose("Long", "a@b.test", ALANA_ADDRESS, when(3, 2), "word " * (CONFIG.body_chars // 5 + 500),
                                       message_id="<long@x.test>"))
    got = read(world, listed(world, "Long")["id"])
    assert got["truncated"] is True and got["total_chars"] <= CONFIG.body_chars


def test_a_message_is_read_a_page_at_a_time(world: World, alana: Box) -> None:
    alana.account.seed("INBOX", compose("Pages", "a@b.test", ALANA_ADDRESS, when(3, 2), "0123456789" * 30, message_id="<p@x.test>"))
    ident = listed(world, "Pages")["id"]
    got = read(world, ident, start=100)
    assert got["start"] == 100 and got["text"].startswith("0123456789") and got["total_chars"] >= 300


def test_reading_and_searching_leave_the_unread_state_as_it_was(world: World, alana: Box) -> None:
    stock(alana)
    ident = listed(world, SUBJECTS[M1])["id"]
    read(world, ident)
    rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, text="ten dollars"))
    assert alana.account.unread(M1) is True
    assert listed(world, SUBJECTS[M1])["unread"] is True


def test_an_id_that_is_no_message_of_this_mailbox_is_not_found(world: World, alana: Box) -> None:
    stock(alana)
    failed(world.turn().call(READ, mailbox=ALANA_ADDRESS, id="<nobody@nowhere.test>"), "not_found")
    failed(world.turn().call(READ, mailbox=ALANA_ADDRESS, id="12345"), "not_found")


def test_the_tools_name_no_provider_field(world: World, alana: Box) -> None:
    stock(alana)
    text = world.turn().call(SEARCH, mailbox=ALANA_ADDRESS).content + world.turn().call(LABELS, mailbox=ALANA_ADDRESS).content
    for word in ("Labels/", "All Mail", "UID", "uidvalidity", "\\\\Seen", "BODY["):
        assert word not in text, word
