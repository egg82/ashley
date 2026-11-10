"""Directed tests for the mutants the blind contract tests let live (written by the reconciler, who had the adapter; the
contract tests stay blind). Each names the mutant in `mutants.txt` it kills."""

import dataclasses
import socket
from typing import Any

import pytest
from ashley import services
from ashley.mail import compose
from ashley.mail.imap import ImapMailbox
from ashley.mail.imap_terms import criteria, terms
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Draft, MailFailed, MailQuery
from ashley.mail.proton_kind import PROTON
from ashley.mail.routed import RoutedMailbox
from mail_proton_blind_store_support import compose as raw, when
from mail_proton_blind_support import (ALANA_ADDRESS, CONFIG, DRAFT, LABEL, M2, READ, SEARCH, SEND, SUBJECTS, Box, World, data,
                                       failed, rows, snapshot, stock, target)
from test_mp_held import SENDS, tainted


def test_a_third_page_follows_the_cursor_of_the_second(world: World, alana: Box) -> None:
    """R7: a cursor that forgets the offset repeats the second page for the third."""
    for n in range(2 * CONFIG.search_max + 6):
        sent = when(4, 1 + n // 24, n % 24)
        alana.account.seed("INBOX", raw(f"Bulk {n:03d}", "Pat <pat@school.test>", ALANA_ADDRESS, sent, f"body {n}",
                                       message_id=f"<bulk{n}@school.test>"), when=sent)
    seen: list[str] = []
    page = ""
    for _ in range(3):
        got = data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox", page=page))
        seen += [m["id"] for m in got["messages"]]
        page = got["next_page"] or ""
    assert len(seen) == len(set(seen)) == 2 * CONFIG.search_max + 6 and page == ""


def test_a_search_word_is_quoted_and_stripped_of_search_syntax() -> None:
    """R15a, R15b."""
    assert criteria(MailQuery(text="a]b*")).plain == ("TEXT", '"a]b*"')
    assert terms('x"(y){z}\\w') == ["xyzw"]


def test_a_line_break_in_a_header_value_is_refused_when_the_message_is_built() -> None:
    """D10: the adapter does not rely on the tools' argument checks."""
    for bad in (Draft(("a@x.test",), "one\r\nBcc: z@x.test", "b"), Draft(("a@x.test\r\nBcc: z@x.test",), "s", "b")):
        with pytest.raises(MailFailed) as e:
            compose.message(bad)
        assert e.value.reason == "refused"


def test_a_draft_with_no_recipient_is_refused_and_nothing_is_appended(world: World, alana: Box) -> None:
    """D12."""
    before = list(alana.account.commands)
    failed(world.turn().call(DRAFT, mailbox=ALANA_ADDRESS, to=[], subject="s", body="b"))
    failed(world.turn().call(DRAFT, mailbox=ALANA_ADDRESS, to=[], cc=["a@x.test"], subject="s", body="b"))
    assert alana.account.commands == before


def test_a_target_that_shows_no_sender_is_not_a_message_with_one(world: World, alana: Box) -> None:
    """L8c: an empty `from` or `subject` matches only an empty value."""
    stock(alana)
    before = snapshot(alana)
    found = {r["subject"]: r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))}
    for blank in ("from", "subject"):
        shown: dict[str, Any] = {**target(found[SUBJECTS[M2]]), blank: ""}
        failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[shown], add=["School"]), "refused")
    assert snapshot(alana) == before


def test_the_same_held_send_asked_twice_runs_once(world: World, alana: Box) -> None:
    """O3b."""
    stock(alana)
    turn = tainted(world, READ)
    turn.call(SEND, **SENDS)
    turn.call(SEND, **SENDS)
    assert not world.guarded().carry_out().is_error
    assert len(world.bridge.smtp.delivered) == 1


def test_a_label_is_the_same_message_in_its_folder_flags_included(world: World, alana: Box) -> None:
    """Q1: a label's copy shares the message's flags, as Bridge's COPY makes it; a re-append would drop \\Seen."""
    stock(alana)
    found = {r["subject"]: r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))}
    assert not world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(found[SUBJECTS[M2]])], add=["School"]).is_error
    (copy,) = [c for c in alana.account.folders["Labels/School"].copies if c.mail.message_id == M2]
    assert "\\Seen" in copy.mail.flags


def wrong_pin(world: World) -> None:
    async def beat() -> None:
        assert await world.record().heartbeat(world.epoch, "00" * 32)

    world.run(beat)


def test_a_certificate_that_is_not_the_pinned_one_is_unreachable_and_no_password_is_sent(world: World, alana: Box) -> None:
    """T1, T2, T3: IMAP and SMTP both check the pin before sending the login."""
    stock(alana)
    wrong_pin(world)
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "unreachable")
    failed(world.turn().call(SEND, mailbox=ALANA_ADDRESS, to=["a@x.test"], subject="s", body="b"), "unreachable")
    assert world.bridge.smtp.attempts == 0 and world.bridge.smtp.delivered == []
    assert alana.account.logins == 0


def test_a_server_that_never_answers_is_unreachable_after_the_timeout(world: World, alana: Box) -> None:
    """Q2."""
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(4)
        port = silent.getsockname()[1]
        quick = dataclasses.replace(CONFIG, timeout_s=1)
        services.register(Mailbox, RoutedMailbox({PROTON.name: ImapMailbox(("127.0.0.1",), quick, port, port)}))
        failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "unreachable")
        failed(world.turn().call(SEND, mailbox=ALANA_ADDRESS, to=["a@x.test"], subject="s", body="b"), "unreachable")
