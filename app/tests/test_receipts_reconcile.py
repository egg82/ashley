"""A woken turn that kept quiet after a judged change still shows the person its receipts: one receipt-only push to the
speaker's phone, as a voice turn sends, and none when her reply goes out with them."""

import logging

import pytest
from ashley import services
from ashley.channels import history_receipts
from ashley.channels.discord import receipt_lines
from ashley.channels.discord.config import load as discord_load
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Pushed
from ashley.channels.storing import stored
from ashley.conversations.model import Receipt, Receipts
from ashley.conversations.quiet import QUIET
from ashley.initiative.initiative import Initiative
from initiative_support import speaking
from ashley.inference.reply import Reply
from ashley.people.model import Person
from ashley.tools import outside_config
from ashley.senses.proposal_payloads import OUTSIDE, HeldCall, HeldCalls, encode

DONE = Receipts((Receipt("Moved an email to a folder", "Moved an email to a folder (folder: archive)", "You asked."),))
HELD = Receipts((), (Receipt("Sent an email", "Sent an email (to: [\"a@b.test\"])", None),), 9)
ALANA = Person(1, 7, "Alana")


@pytest.fixture(autouse=True)
def initiative() -> None:
    services.register(Initiative, speaking())


def woken(thread: str = "household:7") -> Inbound:
    return Inbound(household_id=7, thread=thread, text="a watch fired", kind="chat", medium="text", audience="owner",
                   speaker_id=1, shared=False, place=None, channel="web", later=True, unprompted=True, author="household")


def reply(worth: bool) -> Reply:
    return Reply(spoken="ok", text="Handled it.", says="reply" if worth else "none")


def test_a_quiet_woken_turn_sends_its_receipts_alone_to_the_phone() -> None:
    turn, queued = stored(reply(False), woken(), ALANA, 1, 31, 5, (), DONE)
    assert turn.text == QUIET and turn.receipts == DONE
    assert queued == (Pushed(7, "push:1", Outbound(31, "text", "", receipts=DONE)),)




def test_a_woken_turn_that_speaks_queues_no_receipt_only_push() -> None:
    turn, queued = stored(reply(True), woken(), ALANA, 1, 31, 5, (), DONE)
    assert turn.text == "Handled it." and queued == ()


def test_a_quiet_woken_turn_with_no_receipts_sends_nothing() -> None:
    _, queued = stored(reply(False), woken(), ALANA, 1, 31, 5, (), None)
    assert queued == ()


def test_a_quiet_woken_turn_with_no_phone_to_reach_logs_counts_and_queues_nothing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    _, queued = stored(reply(False), woken(), ALANA, None, 31, 5, (), DONE)
    assert queued == ()
    [line] = [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == "receipts.unshown"]
    assert line == {"conversation": 31, "medium": "text", "done": 1, "held": 0}
    assert "Moved an email" not in repr([r.__dict__ for r in caplog.records])


def test_a_written_turn_nobody_woke_queues_none() -> None:
    asked = Inbound(household_id=7, thread="person:1:web", text="do it", kind="chat", medium="text", audience="owner",
                    speaker_id=1, shared=False, place=None, channel="web", later=True)
    assert stored(reply(False), asked, ALANA, 1, 31, 5, (), DONE)[1] == ()


def test_a_held_call_keeps_its_label_through_the_store_and_one_stored_before_labels_reads_empty() -> None:
    calls = HeldCalls((HeldCall("mail_send", {"to": "a"}, "Sent an email (to: \"a\")", "why", "Sent an email"),))
    topic, raw = encode(calls)
    assert topic == OUTSIDE.name and OUTSIDE.decode(raw) == calls
    for c in raw["calls"]:
        del c["label"]
    assert OUTSIDE.decode(raw).calls[0].label == ""


def test_the_history_line_names_a_part_only_for_what_there_is() -> None:
    words = outside_config.load()
    waiting, done = words.history_held.split("{")[0].strip(), words.history_done.split("{")[0].strip()
    assert waiting not in history_receipts.line(DONE) and done in history_receipts.line(DONE)
    assert done not in history_receipts.line(HELD) and waiting in history_receipts.line(HELD)


def test_a_held_detail_that_runs_over_lines_stays_subtext_on_every_line() -> None:
    wrapped = Receipts((), (Receipt("Sent an email", "first\nsecond\n\nthird", "why\nmore"),), 3)
    text = receipt_lines(wrapped, discord_load())
    assert text is not None and all(line.startswith("-# ") for line in text.splitlines())
