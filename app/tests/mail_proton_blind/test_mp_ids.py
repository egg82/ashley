"""A Proton message's id is its `Message-ID` header, so it survives what Bridge does when it resyncs (design: "for Proton
the `Message-ID` header (a hash of date, sender and subject for a message with none), since Bridge assigns new UIDs when it
resyncs and an id she was given before a failover must still find its message")."""

from datetime import datetime

from mail_proton_blind_store_support import compose, when
from mail_proton_blind_support import ALANA_ADDRESS, CONFIG, M1, M2, M3, READ, SEARCH, SUBJECTS, Box, World, data, rows, stock


def ids(world: World, **query: object) -> dict[str, str]:
    return {r["subject"]: r["id"] for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, **query))}


def text_of(world: World, ident: str) -> str:
    return str(data(world.turn().call(READ, mailbox=ALANA_ADDRESS, id=ident))["text"])


def test_an_id_is_the_message_id_header(world: World, alana: Box) -> None:
    stock(alana)
    got = ids(world)
    assert "m1@school.test" in got[SUBJECTS[M1]] and "m2@shop.test" in got[SUBJECTS[M2]]
    assert len(set(got.values())) == len(got) and not any(i.isdigit() for i in got.values())


def test_the_same_message_in_its_folder_and_its_label_has_one_id(world: World, alana: Box) -> None:
    stock(alana)
    assert ids(world, label="School")[SUBJECTS[M1]] == ids(world, folder="inbox")[SUBJECTS[M1]] == ids(world)[SUBJECTS[M1]]


def test_ids_and_reads_survive_a_resync_that_renumbers_every_uid(world: World, alana: Box) -> None:
    stock(alana)
    before = ids(world)
    held = text_of(world, before[SUBJECTS[M1]])
    alana.account.renumber()
    assert ids(world) == before
    assert text_of(world, before[SUBJECTS[M1]]) == held
    assert text_of(world, before[SUBJECTS[M2]]).strip() == "Pay by Friday"


def test_an_id_read_before_a_resync_finds_a_message_that_is_now_only_in_another_folder(world: World, alana: Box) -> None:
    stock(alana)
    before = ids(world)
    alana.account.renumber()
    assert "ten dollars" in text_of(world, before[SUBJECTS[M1]])
    assert "Soup" in text_of(world, before[SUBJECTS[M3]])


def test_a_message_with_no_message_id_gets_one_that_is_stable_and_its_own(world: World, alana: Box) -> None:
    for subject, sent in (("Anonymous one", when(3, 1)), ("Anonymous two", when(3, 1)), ("Anonymous one", when(3, 9))):
        alana.account.seed("INBOX", compose(subject, "Pat <pat@school.test>", ALANA_ADDRESS, sent, f"{subject} {sent.day}",
                                           message_id=None), when=sent)
    before = sorted((r["subject"], r["date"], r["id"]) for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)))
    assert len({i for _, _, i in before}) == 3 and all(i for _, _, i in before)
    alana.account.renumber()
    after = sorted((r["subject"], r["date"], r["id"]) for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)))
    assert after == before
    for subject, date, ident in before:
        assert text_of(world, ident).startswith(subject) and text_of(world, ident).endswith(str(datetime.fromisoformat(date).day))


def test_an_id_a_search_gives_is_one_the_read_tool_takes_even_for_a_long_message_id(world: World, alana: Box) -> None:
    long_id = "<" + "x" * 110 + "@mail.gmail.test>"
    alana.account.seed("INBOX", compose("Long id", "Pat <pat@school.test>", ALANA_ADDRESS, when(3, 1), "long id body",
                                       message_id=long_id))
    (row,) = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    assert 0 < len(row["id"]) <= CONFIG.message_id_chars
    assert text_of(world, row["id"]).strip() == "long id body"
    alana.account.renumber()
    assert text_of(world, row["id"]).strip() == "long id body"


def test_a_message_id_with_odd_characters_is_read_by_its_id(world: World, alana: Box) -> None:
    odd = "<a+b=c.d$e%f/g@weird-host.test>"
    alana.account.seed("INBOX", compose("Odd id", "Pat <pat@school.test>", ALANA_ADDRESS, when(3, 1), "odd body", message_id=odd))
    (row,) = rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))
    assert text_of(world, row["id"]).strip() == "odd body"


def test_two_messages_whose_ids_differ_only_in_case_or_host_stay_two(world: World, alana: Box) -> None:
    pairs: tuple[tuple[str, str], ...] = (("One", "<same@a.test>"), ("Two", "<same@b.test>"))
    for subject, mid in pairs:
        alana.account.seed("INBOX", compose(subject, "Pat <pat@school.test>", ALANA_ADDRESS, when(3, 1), f"{subject} body", message_id=mid))
    got = ids(world)
    assert got["One"] != got["Two"] and text_of(world, got["One"]).startswith("One") and text_of(world, got["Two"]).startswith("Two")


def test_the_id_of_another_mailboxs_message_is_not_found_here(world: World, alana: Box) -> None:
    stock(alana)
    other = world.box("sam@proton.test", who="sam")
    other.account.seed("INBOX", compose("Sams", "x@y.test", "sam@proton.test", when(3, 1), "sam only", message_id="<sam1@y.test>"))
    (theirs,) = rows(world.turn("sam").call(SEARCH, mailbox="sam@proton.test"))
    got = world.turn().call(READ, mailbox=ALANA_ADDRESS, id=theirs["id"])
    assert got.is_error and "not_found" in got.content
