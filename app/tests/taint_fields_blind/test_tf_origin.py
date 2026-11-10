"""`Inbound.taint`, set by the code that builds each kind of turn: a watch's wake `watch`, a guild
message from nobody in a household `stranger`, and a house wake, a person's own message, a reminder, a bench's reaction
and a household member's Discord message are null."""

from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from ashley.channels.discord.route import route
from ashley.channels.model import DiscordServer, Inbound, on_bench
from ashley.channels.wake import bench_react_turn, reminder_turn, wake_turn, watch_turn
from ashley.criteria.record import Change
from ashley.people.model import Person
from ashley.senses.wakes import Reminder, Wake, WatchWake
from ashley.watches.rows import changed_wake
from ashley.workshop.reactions import Done, Unseen
from ashley.workshop.wake_rule import WakeRule
from discord_support import ALANA, CHANNEL, FAMILY, GUEST_ID, GUILD, ME, message
from watch_job_support import NOW, watch as a_watch
from watch_session_support import SESSION

SERVERS = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)}
SAM = Person(2, 1, "Sam")
SAM_ELSEWHERE = Person(9, 2, "Sam")


def a_web_inbound(**changes: object) -> Inbound:
    base = Inbound(1, "web:1", "hello", "chat", "text", "owner", 2, False, None, "web")
    return replace(base, **changes)


def watch_wake() -> WatchWake:
    before, after = {"status": "working", "seq": 1001}, {"status": "done", "seq": 1002}
    return WatchWake(1, 7, 1, "changed", changed_wake(1, NOW, False, (Change(SESSION, "changed", before, after),)))


def test_an_inbound_is_untainted_unless_its_builder_says_otherwise() -> None:
    assert a_web_inbound().taint is None


@pytest.mark.parametrize("origin", ["watch", "stranger"])
def test_the_origins_are_kept_on_the_inbound(origin: str) -> None:
    made = a_web_inbound(taint=origin)
    assert made.taint == origin
    assert made != a_web_inbound(), "control: taint is part of what an Inbound is"


def test_a_house_wake_does_not_taint_by_origin() -> None:
    wake = Wake(1, "evt-1", "arrived", "person.sam", "front_door", datetime(2026, 11, 5, 12, 0, tzinfo=UTC))
    made = wake_turn.inbound(5, wake, WakeRule("arrived", "Greet them.", ("look",)), SAM)
    assert made.taint is None
    assert made.unprompted and made.source == "wake:5", "control: this is the wake's turn"


@pytest.mark.parametrize("handoff", [False, True])
@pytest.mark.parametrize("bench", [False, True])
def test_a_watch_of_an_outside_kind_is_a_watch_turn_wherever_it_runs(bench: bool, handoff: bool) -> None:
    watch_ = replace(a_watch(person=7, kind="no_such_kind"), bench_id=5, armed_by="handoff" if handoff else "ashley")
    made = watch_turn.inbound(9, watch_, watch_wake(), bench)
    assert made.taint == "watch"
    assert made.thread == ("bench:5" if bench else "push:7"), "control: both places were built"


def test_a_reminder_firing_is_not_tainted() -> None:
    made = reminder_turn.inbound(7, Reminder(1, 2, 3, "Pay the bill.", datetime.now(UTC), None), SAM,
                                 Person(3, 1, "Alana"))
    assert made.taint is None
    assert made.promised and made.source == "wake:7", "control: this is the reminder's turn"


def test_a_benchs_reaction_to_the_persons_change_is_not_tainted() -> None:
    unseen = Unseen(5, 1, 2, 0, 3, 1, (Done(3, "edit", 8, "note", datetime(2026, 11, 5, 12, 0, tzinfo=UTC)),))
    made = bench_react_turn.inbound(unseen, ZoneInfo("America/Denver"))
    assert made.taint is None
    assert made.unprompted and made.watched, "control: this is the reaction's turn"


def test_a_talk_on_a_bench_is_not_tainted() -> None:
    assert on_bench(1, 2, 5, "move it left").taint is None


def test_a_guild_message_from_someone_in_no_household_is_a_stranger_turn() -> None:
    made = route(message(author_id=GUEST_ID), ME, SERVERS, None)
    assert made is not None and made.taint == "stranger"
    assert made.speaker_id is None, "control: this is the message by nobody in the house"


def test_tf_a_guild_message_from_a_member_of_another_household_is_a_stranger_turn() -> None:
    made = route(message(author_id=GUEST_ID), ME, SERVERS, SAM_ELSEWHERE)
    assert made is not None and made.taint == "stranger"
    assert made.speaker_id is None, "control: she is not a speaker in this household"


def test_a_guild_message_from_a_household_member_is_not_tainted() -> None:
    made = route(message(), ME, SERVERS, ALANA)
    assert made is not None and made.taint is None
    assert made.speaker_id == ALANA.id


def test_a_dm_from_a_household_member_is_not_tainted() -> None:
    dm = message(guild_id=None, channel_id=2001, mentions_me=False)
    made = route(dm, ME, SERVERS, ALANA)
    assert made is not None and made.taint is None
    assert made.thread == "discord:2001"


def test_a_stranger_only_taints_the_message_that_reaches_her() -> None:
    assert route(message(author_id=GUEST_ID, mentions_me=False), ME, SERVERS, None) is None
