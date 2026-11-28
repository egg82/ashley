"""Which turns are unasked, and what caused them, comes from the turn's fields: each builder of a turn no person's message
starts names its cause (a wake, a reminder, an errand's check, a standing errand's round, a watch, a bench), the
standing of an unprompted turn is unasked with that cause and a person's own message is not, and a checkpoint keeps the
cause so a runner that resumes the turn records what the first would have."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashley.channels import checkpoint, standing
from ashley.channels.model import Inbound
from ashley.channels.tool_loop import Progress
from ashley.channels.wake import bench_react_turn, reminder_turn, wake_turn, watch_turn
from ashley.inference.model import SystemPrompt
from ashley.people.model import Person
from ashley.senses.outside_record import Cause
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder, Wake, WatchWake
from ashley.workshop.reactions import Done, Unseen
from ashley.workshop.wake_rule import WakeRule
from watch_job_support import watch as a_watch

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
SAM = Person(7, 1, "Sam")
DAILY = Repeat("daily", 1, datetime(2026, 11, 27, 12))


def reminder(**changes: object) -> Reminder:
    return replace(Reminder(1, SAM.id, SAM.id, "water the plants", NOW, None), **changes)


@pytest.mark.parametrize(("made", "cause"), [
    (reminder(), Cause("reminder", 55)),
    (reminder(ends_at=NOW + timedelta(days=2)), Cause("open_errand", 55)),
    (reminder(repeat=DAILY, method="price_watch"), Cause("standing_errand", 55))])
def test_a_reminder_turn_names_its_occurrence_by_what_kind_of_reminder_it_is(made: Reminder, cause: Cause) -> None:
    turn = reminder_turn.inbound(55, made, SAM, SAM)
    assert turn.cause == cause
    assert turn.unprompted


def test_a_wake_a_watch_and_a_bench_reaction_each_name_their_own_record() -> None:
    woke = wake_turn.inbound(41, Wake(1, "e1", "arrived", None, None, NOW), WakeRule("arrived", "say hi", ()), SAM)
    watched = watch_turn.inbound(42, a_watch(9), WatchWake(1, 7, 9, "paused", {}), on_bench=False)
    reacted = bench_react_turn.inbound(Unseen(12, 1, 7, 0, 3, 1, (Done(3, "add", None, None, NOW),)), UTC)
    assert (woke.cause, watched.cause, reacted.cause) == (Cause("wake", 41), Cause("watch", 9), Cause("bench", 12))
    assert woke.unprompted and watched.unprompted and reacted.unprompted


def person_message(**changes: object) -> Inbound:
    said = Inbound(household_id=1, thread="web:7", text="turn the lamp on", kind="chat", medium="text",
                   audience="owner", speaker_id=SAM.id, shared=False, place=None, channel="web")
    return replace(said, **changes)


def test_an_unprompted_turn_stands_unasked_with_its_cause_and_a_persons_message_does_not() -> None:
    own = standing.of(person_message())
    woke = standing.of(reminder_turn.inbound(55, reminder(), SAM, SAM))
    assert own is not None and woke is not None
    assert (own.unasked, own.cause) == (False, None)
    assert (woke.unasked, woke.cause) == (True, Cause("reminder", 55))


def test_a_cause_on_a_persons_own_message_does_not_make_it_unasked() -> None:
    got = standing.of(person_message(cause=Cause("wake", 1)))
    assert got is not None and (got.unasked, got.cause) == (False, None)


def saved(inbound: Inbound) -> str:
    return checkpoint.dumps(checkpoint.Checkpoint(inbound, 1, 2, 7, {"default": SystemPrompt("s")}, Progress((), 0, 0)))


def test_a_checkpoint_keeps_the_cause_and_a_turn_saved_before_causes_reads_back_with_none() -> None:
    woke = reminder_turn.inbound(55, reminder(ends_at=NOW + timedelta(days=1)), SAM, SAM)
    assert checkpoint.loads(saved(woke)).inbound.cause == Cause("open_errand", 55)
    old = saved(person_message()).replace(', "cause": null', "")
    assert '"cause"' not in old, "the saved turn has no cause key: control"
    assert checkpoint.loads(old).inbound.cause is None


def test_a_checkpoint_with_a_cause_this_release_does_not_know_is_refused() -> None:
    text = saved(person_message(cause=Cause("wake", 3))).replace('"kind": "wake"', '"kind": "rumour"')
    assert '"rumour"' in text
    with pytest.raises(ValueError):
        checkpoint.loads(text)
