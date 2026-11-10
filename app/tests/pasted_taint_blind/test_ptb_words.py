"""WORDS (design 3.1): the block a person pasted or forwarded with a message is never among the judge's words; the typed
text beside it stays; it is left out wherever the message sits in the conversation and whichever turn asks, and a woken
turn made by a pasted turn gets it neither."""

from datetime import timedelta

import pytest
from ashley.channels.wake import reminder_turn
from ashley.people.model import Person
from ashley.senses.wakes import Reminder
from ashley.channels.discord.route import FORWARD_ONLY, route
from ashley.channels.model import DiscordServer
from ashley.conversations.model import Attachment
from discord_support import ALANA as DISCORD_ALANA, CHANNEL, FAMILY, GUILD, ME, message as discord_message
from pasted_taint_blind_support import ALANA, NOW, ORIGIN, SAM, TYPED_A, TYPED_B, inbound, message, over, person_turn, read

TOKEN = "PASTE-9f2c7a"  # gitleaks:allow (test fixture)


def clean(got: tuple[str, ...]) -> bool:
    return not any(TOKEN in w or "mallory" in w for w in got)


def test_the_pasted_block_is_cut_and_the_typed_text_beside_it_stays() -> None:
    text, span = message(over())
    got = read(inbound(taint=ORIGIN), person_turn(1, text, [span]))
    assert clean(got) and len(got) == 1
    assert TYPED_A.strip() in got[0] and TYPED_B.strip() in got[0]


def test_a_later_message_leaves_out_the_block_of_an_earlier_one() -> None:
    text, span = message(over())
    got = read(inbound(), person_turn(1, text, [span]), person_turn(2, "and the den"))
    assert clean(got) and got[-1] == "and the den" and TYPED_A.strip() in got[0]


def test_a_turn_with_nothing_pasted_reads_whole() -> None:
    got = read(inbound(taint=ORIGIN), person_turn(1, "turn on the porch light"))
    assert got == ("turn on the porch light",)


def test_a_message_that_is_only_a_forward_leaves_none_of_the_forward() -> None:
    forwarded = route(discord_message(content="", forwarded=over()), ME, {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)},
                      DISCORD_ALANA)
    assert forwarded is not None and forwarded.attachment is not None
    got = read(inbound(taint=ORIGIN), person_turn(1, forwarded.text, [forwarded.attachment]), person_turn(2, "yes do that"))
    assert clean(got) and got == (FORWARD_ONLY, "yes do that")


def test_the_typed_text_is_cut_to_its_length_alone_so_the_block_spends_none_of_it() -> None:
    typed = TYPED_A + "then lock up"
    got = read(inbound(taint=ORIGIN), person_turn(1, typed, [Attachment(None, over())]), chars=len(typed))
    assert got == (typed,)


def test_another_speakers_message_is_never_words_pasted_or_not() -> None:
    text, span = message(over())
    got = read(inbound(taint=ORIGIN), person_turn(1, text, [span], speaker=SAM), person_turn(2, "mine"))
    assert got == ("mine",)


def test_every_block_is_left_out_whichever_message_carries_it() -> None:
    one, two = over(), over().replace("PASTE-9f2c7a", "PASTE-second")
    got = read(inbound(taint=ORIGIN), person_turn(1, "first " + TYPED_A, [Attachment(None, one)]),
               person_turn(2, "middle", []), person_turn(3, "second " + TYPED_B, [Attachment("Forwarded", two)]))
    assert clean(got) and len(got) == 3
    assert not any("PASTE-" in w for w in got) and got[0].startswith("first") and got[2].startswith("second")


def test_a_woken_turn_made_by_a_pasted_turn_does_not_get_the_pasted_spans_as_words() -> None:
    text, span = message(over())
    woken = inbound(taint="inherited", made_in=(5, 1), unprompted=True)
    got = read(woken, person_turn(1, text, [span]), person_turn(2, "later, after it"))
    assert clean(got) and TYPED_A.strip() in got[0] and "later, after it" not in got


def test_a_reminder_a_pasted_turn_made_wakes_a_turn_whose_words_are_cut() -> None:
    text, span = message(over())
    made = Reminder(1, ALANA, ALANA, "BRIEF-9d41", NOW + timedelta(days=1), None, taint=ORIGIN, made_in=(5, 1))
    fired = reminder_turn.inbound(3, made, Person(ALANA, 1, "Alana"), Person(ALANA, 1, "Alana"))
    assert fired.taint == "inherited" and fired.made_in == (5, 1)
    got = read(fired, person_turn(1, text, [span]))
    assert clean(got) and TYPED_A.strip() in got[0] and not any("BRIEF" in w for w in got)


@pytest.mark.parametrize("origin", ["stranger", "watch"])
def test_the_other_outside_origins_still_have_no_words(origin: str) -> None:
    assert read(inbound(taint=origin), person_turn(1, "turn on the porch light")) == ()
