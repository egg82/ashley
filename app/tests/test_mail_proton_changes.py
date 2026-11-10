"""The IMAP adapter's changes over a fake Bridge (`mail_proton_support`): a draft appended to Drafts, a send over SMTP that
is never retried, and labels, folders and read state changed by copying and deleting; every target checked against what
the person was shown before anything is changed."""

import asyncio
from collections.abc import Generator
from email import message_from_bytes, policy
from typing import Any

import pytest
from ashley import services
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Draft, MailChange, MailFailed, MailQuery, Target
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
    state.add("INBOX", mail("Field trip", message_id="<trip@school.test>", References="<root@school.test>"), (),
              "07-Nov-2026 10:00:00 +0000")
    state.add("INBOX", mail("Receipt", sender="Shop <shop@store.test>", message_id="<rcpt@store.test>"), ("\\Seen",),
              "06-Nov-2026 09:00:00 +0000")
    return state


def box() -> Mailbox:
    return services.get(Mailbox)


def failure(coro: Any) -> str:
    with pytest.raises(MailFailed) as e:
        asyncio.run(coro)
    return e.value.reason


def target(ident: str = "trip@school.test", sender: str = "Sam", subject: str = "Field") -> Target:
    return Target(ident, sender, subject)


def snapshot(bridge: Bridge) -> dict[str, list[tuple[int, frozenset[str]]]]:
    return {f: [(s.uid, frozenset(s.flags)) for s in items] for f, items in bridge.folders.items()}


def test_a_draft_is_appended_to_drafts_flagged_and_its_id_is_its_message_id(bridge: Bridge) -> None:
    ident = asyncio.run(box().draft(ACCOUNT, Draft(("sam@school.test",), "Lunch?", "Noon?", ("kim@school.test",))))
    (stored,) = bridge.folders["Drafts"]
    assert "\\Draft" in stored.flags
    parsed = message_from_bytes(stored.raw, policy=policy.default)
    assert (parsed["From"], parsed["To"], parsed["Cc"], parsed["Subject"]) == (USER, "sam@school.test", "kim@school.test", "Lunch?")
    assert parsed["Message-ID"].strip("<>") == ident and parsed["Date"]
    assert asyncio.run(box().read(ACCOUNT, ident)).body == "Noon?"
    assert bridge.sent == []


def test_a_draft_answering_a_message_is_threaded_under_it(bridge: Bridge) -> None:
    asyncio.run(box().draft(ACCOUNT, Draft(("sam@school.test",), "Re: Field trip", "Yes", reply_to="trip@school.test")))
    parsed = message_from_bytes(bridge.folders["Drafts"][0].raw, policy=policy.default)
    assert parsed["In-Reply-To"] == "<trip@school.test>"
    assert parsed["References"] == "<root@school.test> <trip@school.test>"


def test_a_draft_answering_none_of_this_mailboxs_is_not_found_and_saves_nothing(bridge: Bridge) -> None:
    assert failure(box().draft(ACCOUNT, Draft(("a@b.test",), "s", "b", reply_to="nothing@x.test"))) == "not_found"
    assert bridge.folders["Drafts"] == []


def test_a_header_with_a_line_break_in_it_is_refused(bridge: Bridge) -> None:
    assert failure(box().draft(ACCOUNT, Draft(("a@b.test",), "s\nBcc: x@y.test", "b"))) == "refused"
    assert failure(box().send(ACCOUNT, Draft(("a@b.test",), "s\nBcc: x@y.test", "b"))) == "refused"
    assert bridge.sent == [] and bridge.folders["Drafts"] == []


def test_a_send_goes_over_smtp_to_every_recipient_from_the_address_and_gives_its_message_id(bridge: Bridge) -> None:
    ident = asyncio.run(box().send(ACCOUNT, Draft(("sam@school.test",), "Lunch?", "Noon?", ("kim@school.test",))))
    ((sender, rcpts, raw),) = bridge.sent
    parsed = message_from_bytes(raw, policy=policy.default)
    assert sender == USER and rcpts == ["sam@school.test", "kim@school.test"]
    assert (parsed["From"], parsed["Subject"], parsed["Message-ID"].strip("<>")) == (USER, "Lunch?", ident)
    assert parsed.get_content().strip() == "Noon?"
    assert bridge.logins == 0 and bridge.commands == []


def test_a_send_answering_a_message_looks_it_up_over_imap_and_threads_under_it(bridge: Bridge) -> None:
    asyncio.run(box().send(ACCOUNT, Draft(("sam@school.test",), "Re: Field trip", "Yes", reply_to="trip@school.test")))
    parsed = message_from_bytes(bridge.sent[0][2], policy=policy.default)
    assert parsed["In-Reply-To"] == "<trip@school.test>" and bridge.logins == 1


def test_a_recipient_bridge_refuses_is_refused_and_nothing_is_sent(bridge: Bridge) -> None:
    bridge.refuse.add("nobody@x.test")
    assert failure(box().send(ACCOUNT, Draft(("nobody@x.test",), "s", "b"))) == "refused"
    assert bridge.sent == []


def test_a_password_smtp_refuses_needs_reconnect(bridge: Bridge) -> None:
    bridge.password = "rotated"
    assert failure(box().send(ACCOUNT, Draft(("a@b.test",), "s", "b"))) == "needs_reconnect"


def test_a_send_is_made_once_even_when_the_connection_drops_after_the_data(bridge: Bridge, fake: FakeBridge,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    def dropped(self: smtplib.SMTP, *args: Any, **kwargs: Any) -> Any:
        bridge.sent.append(("", [], b""))
        raise smtplib.SMTPServerDisconnected("gone")

    monkeypatch.setattr(smtplib.SMTP, "sendmail", dropped)
    assert failure(box().send(ACCOUNT, Draft(("a@b.test",), "s", "b"))) == "unreachable"
    assert len(bridge.sent) == 1


def test_a_label_added_is_a_copy_into_its_folder_and_the_message_stays_where_it_was(bridge: Bridge) -> None:
    done = asyncio.run(box().change(ACCOUNT, (target(),), MailChange(add=("school",))))
    assert done == 1
    assert [s.raw for s in bridge.folders["Labels/School"]] == [bridge.folders["INBOX"][0].raw]
    assert len(bridge.folders["INBOX"]) == 2
    found = asyncio.run(box().search(ACCOUNT, MailQuery(subject="field trip"))).items[0]
    assert found.labels == ("School",) and found.folder == "inbox"


def test_a_label_removed_is_a_delete_from_its_folder_alone(bridge: Bridge) -> None:
    bridge.add("Labels/School", bridge.folders["INBOX"][0].raw)
    bridge.add("Labels/School", bridge.folders["INBOX"][1].raw)
    asyncio.run(box().change(ACCOUNT, (target(),), MailChange(remove=("School",))))
    assert [s.raw for s in bridge.folders["Labels/School"]] == [bridge.folders["INBOX"][1].raw]
    assert len(bridge.folders["INBOX"]) == 2


def test_a_move_copies_to_the_folder_and_deletes_from_the_one_it_was_in(bridge: Bridge) -> None:
    assert asyncio.run(box().change(ACCOUNT, (target(),), MailChange(folder="archive"))) == 1
    assert [asyncio.run(box().read(ACCOUNT, "trip@school.test")).header.folder] == ["archive"]
    assert len(bridge.folders["INBOX"]) == 1 and len(bridge.folders["Archive"]) == 1
    asyncio.run(box().change(ACCOUNT, (target(),), MailChange(folder="trash")))
    assert len(bridge.folders["Archive"]) == 0 and len(bridge.folders["Trash"]) == 1


def test_moving_to_the_folder_a_message_is_in_changes_nothing(bridge: Bridge) -> None:
    before = snapshot(bridge)
    assert asyncio.run(box().change(ACCOUNT, (target(),), MailChange(folder="inbox"))) == 1
    assert snapshot(bridge) == before


def test_read_state_is_the_seen_flag(bridge: Bridge) -> None:
    asyncio.run(box().change(ACCOUNT, (target(),), MailChange(unread=False)))
    assert "\\Seen" in bridge.folders["INBOX"][0].flags
    asyncio.run(box().change(ACCOUNT, (target("rcpt@store.test", "Shop", "Receipt"),), MailChange(unread=True)))
    assert "\\Seen" not in bridge.folders["INBOX"][1].flags


def test_one_target_that_is_not_what_the_person_was_shown_changes_none_of_them(bridge: Bridge) -> None:
    before = snapshot(bridge)
    swapped = (target(), target("rcpt@store.test", "Shop", "Something else"))
    assert failure(box().change(ACCOUNT, swapped, MailChange(add=("School",), unread=False))) == "refused"
    assert failure(box().change(ACCOUNT, (target(sender="Mallory"),), MailChange(folder="trash"))) == "refused"
    assert snapshot(bridge) == before


def test_an_id_or_a_label_that_is_none_of_the_mailboxs_changes_nothing(bridge: Bridge) -> None:
    before = snapshot(bridge)
    assert failure(box().change(ACCOUNT, (target("nothing@x.test"),), MailChange(unread=False))) == "not_found"
    assert failure(box().change(ACCOUNT, (target(),), MailChange(add=("Nope",)))) == "not_found"
    assert failure(box().change(ACCOUNT, (target(),), MailChange(remove=("Nope",)))) == "not_found"
    assert snapshot(bridge) == before


def test_a_change_that_changes_nothing_or_contradicts_itself_is_refused(bridge: Bridge) -> None:
    before = snapshot(bridge)
    assert failure(box().change(ACCOUNT, (target(),), MailChange())) == "refused"
    assert failure(box().change(ACCOUNT, (), MailChange(unread=True))) == "refused"
    assert failure(box().change(ACCOUNT, (target(),), MailChange(add=("School",), remove=("school",)))) == "refused"
    assert failure(box().change(ACCOUNT, (target(),), MailChange(folder="elsewhere"))) == "refused"
    assert snapshot(bridge) == before


def test_the_same_message_named_twice_is_changed_once_and_counted_once(bridge: Bridge) -> None:
    assert asyncio.run(box().change(ACCOUNT, (target(), target()), MailChange(add=("School",)))) == 1
    assert len(bridge.folders["Labels/School"]) == 1


def test_a_label_with_a_character_outside_ascii_is_reached_by_its_name(bridge: Bridge) -> None:
    asyncio.run(box().change(ACCOUNT, (target(),), MailChange(add=("café",))))
    assert len(bridge.folders["Labels/Café"]) == 1


def test_a_change_in_a_mailbox_syncing_changes_nothing_and_says_so(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake, synced=False)
    before = snapshot(bridge)
    assert failure(box().change(ACCOUNT, (target(),), MailChange(unread=False))) == "syncing"
    assert failure(box().draft(ACCOUNT, Draft(("a@b.test",), "s", "b"))) == "syncing"
    assert failure(box().send(ACCOUNT, Draft(("a@b.test",), "s", "b"))) == "syncing"
    assert snapshot(bridge) == before and bridge.sent == [] and bridge.logins == 0
