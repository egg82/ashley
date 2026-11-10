"""What each channel does with receipts: her words are stored and sent untouched, a spoken turn says none of them and sends
them to the speaker's phone (once, in the copy when she chose one), Discord gets one small-text message after her words,
a push keeps one notification with the Agree action, a receipts-only push says headlines, her history carries a marked
line, and the wire holds the stored snapshot."""

import logging
from dataclasses import replace

import pytest
from ashley.api.receipt_models import wire_receipts
from ashley.channels import history_receipts, prompt, to_phone
from ashley.channels.discord import receipt_lines
from ashley.channels.discord.config import load as discord_load
from ashley.channels.discord.later import post
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Pushed
from ashley.channels.push import config as push_config
from ashley.channels.push.later import notified
from ashley.channels.storing import pushed, receipt_push, stored
from ashley.conversations.model import Receipt, Receipts, Turn
from ashley.inference.reply import Reply
from ashley.people.model import Household, Person
from ashley.tools import outside_config
from contract.conversations_support import run
from datetime import UTC, datetime
from discord_support import CHANNEL, FakeDiscord
from later_support import waiting

DONE = Receipt("Changed something in the house", "house_do (action: light.turn_on)", "You asked for it.")
HELD = Receipt("Sent an email", 'mail_send (to: ["a@b.test"], body: "hi")', "Not asked for in so many words.")
BOTH = Receipts((DONE,), (HELD,), 7)
DONE_ONLY = Receipts((DONE,))
WORDS = "I did one thing and I am holding another."
REPLY = Reply(spoken="Done.", text=WORDS)
ALANA = Person(1, 7, "Alana")


def spoken() -> Inbound:
    return Inbound(household_id=7, thread="device:77", text="do it", kind="command", medium="spoken", audience="household",
                   speaker_id=1, shared=True, place="kitchen", channel="voice", later=True)


def written() -> Inbound:
    return Inbound(household_id=7, thread="person:1:web", text="do it", kind="chat", medium="text", audience="owner",
                   speaker_id=1, shared=False, place=None, channel="web", later=True)


def no_receipt_text(text: str) -> bool:
    return not any(r.headline in text or (r.detail or "") in text for r in (*BOTH.done, *BOTH.held))


def test_her_stored_turn_keeps_her_words_and_the_receipts_beside_them() -> None:
    turn, queued = stored(REPLY, written(), ALANA, None, 31, 5, (), BOTH)
    assert turn.text == WORDS and turn.receipts == BOTH and queued == ()


def test_a_spoken_turn_stores_what_was_said_and_no_receipt_text() -> None:
    turn, _ = stored(REPLY, spoken(), ALANA, 1, 31, 5, (), BOTH)
    assert turn.text == "Done." and no_receipt_text(turn.text) and turn.spoken is None and turn.receipts == BOTH


def test_a_spoken_turn_with_a_reachable_speaker_queues_exactly_one_receipt_only_push() -> None:
    _, queued = stored(REPLY, spoken(), ALANA, 1, 31, 5, (), BOTH)
    assert queued == (Pushed(7, "push:1", Outbound(31, "text", "", agree=7, receipts=BOTH)),)


def test_when_she_chose_the_phone_the_copy_carries_the_receipts_and_no_second_push_is_queued() -> None:
    sent = REPLY.model_copy(update={"to_phone": True})
    _, queued = stored(sent, spoken(), ALANA, 1, 31, 5, (), BOTH)
    assert queued == (Pushed(7, "push:1", Outbound(31, "text", WORDS, agree=7, receipts=BOTH)),)


def test_an_unreachable_speaker_gets_none_queued_and_the_one_log_line_carries_counts(
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    turn, queued = stored(REPLY, spoken(), ALANA, None, 31, 5, (), BOTH)
    assert queued == () and turn.receipts == BOTH
    [line] = [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == "receipts.unshown"]
    assert line == {"conversation": 31, "medium": "spoken", "done": 1, "held": 1}
    assert HELD.detail is not None and HELD.detail not in repr([r.__dict__ for r in caplog.records])


def test_a_written_reply_queues_no_receipt_push_of_its_own() -> None:
    assert receipt_push(BOTH, written(), 1, 31) is None
    assert receipt_push(None, spoken(), 1, 31) is None


def test_the_reply_queued_for_a_thread_carries_her_words_untouched_and_the_receipts() -> None:
    async def go() -> None:
        got = await pushed(REPLY, written(), 31, BOTH)
        assert got == (Pushed(7, "person:1:web", Outbound(31, "text", WORDS, agree=7, receipts=BOTH)),)
        [bare] = await pushed(REPLY, written(), 31)
        assert bare.outbound.receipts is None and bare.outbound.agree is None

    run(go())


def test_the_phone_copy_of_a_reply_without_receipts_has_none() -> None:
    got = to_phone.copy(REPLY.model_copy(update={"to_phone": True}), 1, 7, 31)
    assert got == Pushed(7, "push:1", Outbound(31, "text", WORDS))


CONFIG = push_config.load()


def test_her_notification_is_her_words_with_the_agree_action_and_no_receipt_text() -> None:
    note = notified(CONFIG, Outbound(31, "text", WORDS, agree=7, receipts=BOTH))
    assert (note.title, note.body, note.agree) == (CONFIG.title, WORDS, 7) and no_receipt_text(note.body)


def test_a_receipts_only_push_says_the_headlines_under_a_title_for_what_it_holds() -> None:
    both = notified(CONFIG, Outbound(31, "text", "", agree=7, receipts=BOTH))
    assert both.title == CONFIG.held_title and both.agree == 7
    assert both.body == "Changed something in the house; Sent an email"
    done = notified(CONFIG, Outbound(31, "text", "", receipts=DONE_ONLY))
    assert done.title == CONFIG.done_title and done.agree is None


def test_a_receipts_only_push_is_cut_to_the_body_limit() -> None:
    many = Receipts(tuple(Receipt("Made a change " + "x" * 50) for _ in range(20)))
    assert len(notified(CONFIG, Outbound(31, "text", "", receipts=many)).body) <= CONFIG.body_chars


DISCORD = discord_load()


def test_the_discord_message_is_all_subtext_done_lines_then_held_lines_in_full_then_the_footer() -> None:
    text = receipt_lines(BOTH, DISCORD)
    assert text is not None and all(line.startswith("-# ") for line in text.split("\n"))
    lines = text.split("\n")
    assert "Changed something in the house" in lines[0] and "mail_send" not in lines[0]
    assert HELD.detail is not None and HELD.detail in lines[1] and lines[-1] == f"-# {DISCORD.held_footer}"
    assert receipt_lines(None, DISCORD) is None


def test_a_done_only_message_has_no_footer_and_fits_one_message_even_for_a_huge_summary() -> None:
    assert DISCORD.held_footer not in (receipt_lines(DONE_ONLY, DISCORD) or "")
    huge = Receipts((), (Receipt("Sent an email", "x" * 5000),), 3)
    text = receipt_lines(huge, DISCORD)
    assert text is not None and len(text) <= 2000 and text.endswith(DISCORD.held_footer)


def test_from_the_outbox_her_chunks_come_first_and_one_receipt_message_last() -> None:
    discord = FakeDiscord()
    later = waiting(f"discord:{CHANNEL}", WORDS, medium="text", age_ms=10)
    later = replace(later, outbound=replace(later.outbound, receipts=BOTH))

    async def go() -> None:
        await post(discord, later, DISCORD)

    run(go())
    texts = discord.texts()
    assert texts[0] == WORDS and len(texts) == 2 and all(line.startswith("-# ") for line in texts[1].split("\n"))
    assert all(no_receipt_text(t) for t in texts[:1])


def test_a_reply_without_receipts_sends_no_extra_discord_message() -> None:
    discord = FakeDiscord()

    async def go() -> None:
        await post(discord, waiting(f"discord:{CHANNEL}", WORDS, medium="text", age_ms=10), DISCORD)

    run(go())
    assert discord.texts() == [WORDS]


HOME = Household(7, "Moore", "America/Chicago", "", (ALANA,))
CFG = outside_config.load()


def hers(receipts: Receipts | None, text: str = WORDS) -> Turn:
    return Turn(2, "ashley", None, text, datetime(2026, 11, 8, 10, tzinfo=UTC), receipts=receipts)


def test_her_history_carries_the_marked_line_on_a_line_of_its_own_after_her_words() -> None:
    line = history_receipts.line(BOTH)
    assert line.startswith(CFG.history_line.split("{")[0]) and "Done: Changed something in the house" in line
    assert f"Waiting for their OK: Sent an email ({HELD.detail})" in line
    said = Turn(1, "person", 1, "do it", datetime(2026, 11, 8, 9, 59, tzinfo=UTC))
    got = prompt.messages([hers(BOTH)], said, HOME)[0].text
    assert got.endswith(f"{WORDS}\n{line}") and got.count("\n") == 1


def test_a_turn_without_receipts_gets_nothing_in_either_history_form() -> None:
    said = Turn(1, "person", 1, "do it", datetime(2026, 11, 8, 9, 59, tzinfo=UTC))
    plain = prompt.messages([hers(None)], said, HOME)[0].text
    assert plain.endswith(WORDS) and "Shown beside" not in plain
    assert prompt.said_before([hers(None)], HOME)[0].endswith(WORDS)
    assert prompt.said_before([hers(BOTH)], HOME)[0].endswith(history_receipts.line(BOTH))


def test_the_wire_holds_the_snapshot_and_none_for_a_turn_without() -> None:
    wired = wire_receipts(BOTH)
    assert wired is not None and wired.proposal_id == 7
    assert [(r.headline, r.detail, r.why) for r in wired.held] == [(HELD.headline, HELD.detail, HELD.why)]
    assert [(r.headline, r.detail) for r in wired.ran] == [(DONE.headline, DONE.detail)]
    assert wire_receipts(None) is None


def test_receipts_round_trip_through_json_and_refuse_what_shows_nothing_or_names_no_proposal() -> None:
    assert Receipts.from_json(BOTH.to_json()) == BOTH
    with pytest.raises(ValueError):
        Receipts()
    with pytest.raises(ValueError):
        Receipts(held=(HELD,))
    with pytest.raises(ValueError):
        Receipts(done=(DONE,), proposal_id=3)
