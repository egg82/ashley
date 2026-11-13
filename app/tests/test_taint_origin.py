"""`Inbound.taint`: what outside started a turn, set where each kind of turn is built. A watch's wake of a kind whose
reads can carry outside text is `watch`, a Discord server message by an author in no household a `stranger`; a house
wake, a watch of a kind that cannot, a person's own message, a reminder, a bench's reaction and a voice in a room
are None."""

from dataclasses import replace
from datetime import UTC, datetime

from ashley.channels.discord.route import route
from ashley.channels.model import DiscordServer, Inbound, on_bench
from ashley.channels.wake import reminder_turn, wake_turn, watch_turn
from ashley.people.model import Person
from ashley.watches.registry import KINDS
from ashley.senses.wakes import Reminder, Wake, WatchWake
from ashley.workshop.wake_rule import WakeRule
from ashley.initiative.moment import Moment
from discord_support import ALANA, CHANNEL, DM_CHANNEL, FAMILY, GUILD, ME, message
from watch_job_support import watch as a_watch

SERVERS = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)}
PERSON = Person(7, 1, "Alana")


def test_an_inbound_is_untainted_unless_its_builder_says_so() -> None:
    plain = Inbound(1, "t", "x", "chat", "text", "owner", 1, False, None, "web", taint=None)
    assert plain.taint is None and replace(plain, taint="watch").taint == "watch"


def test_a_house_wake_is_untainted() -> None:
    wake = Wake(1, "e1", "arrived", "person.alana", "home", datetime(2026, 11, 6, tzinfo=UTC))
    assert wake_turn.inbound(5, wake, WakeRule("arrived", "greet", ()), PERSON, Moment("wake:5"), "full").taint is None


def test_a_watch_of_an_outside_kind_is_tainted_on_the_phone_thread_and_on_its_bench() -> None:
    wake = WatchWake(1, 7, 1, "paused", {"reason": "unreadable"})
    unknown = a_watch(kind="no_such_kind")
    phone = watch_turn.inbound(3, unknown, wake, on_bench=False)
    benched = watch_turn.inbound(3, replace(unknown, bench_id=9), wake, on_bench=True)
    assert phone.taint == "watch"
    assert benched.thread != phone.thread and benched.taint == "watch", "control: the bench turn is another thread"


def test_a_claude_session_watch_is_untainted_on_the_phone_thread_and_on_its_bench() -> None:
    wake = WatchWake(1, 7, 1, "paused", {"reason": "unreadable"})
    phone = watch_turn.inbound(3, a_watch(), wake, on_bench=False)
    benched = watch_turn.inbound(3, replace(a_watch(), bench_id=9), wake, on_bench=True)
    assert phone.taint is None and benched.taint is None
    assert benched.thread != phone.thread, "control: the bench turn is another thread"


def test_only_the_shipped_session_kind_reads_no_outside_text() -> None:
    assert KINDS.get("claude_session").outside is False
    assert KINDS.get("no_such_kind").outside is True


def test_a_reminder_firing_is_untainted() -> None:
    reminder = Reminder(1, 7, 7, "water", datetime(2026, 11, 6, tzinfo=UTC), None)
    assert reminder_turn.inbound(3, reminder, PERSON, PERSON).taint is None


def test_a_message_in_a_server_by_someone_in_no_household_is_a_stranger() -> None:
    stranger = route(message(), ME, SERVERS, None)
    assert stranger is not None and stranger.taint == "stranger"
    member = route(message(), ME, SERVERS, ALANA)
    assert member is not None and member.taint is None, "control: the same message by a household member"


def test_a_direct_message_is_untainted() -> None:
    got = route(message(guild_id=None, channel_id=DM_CHANNEL, mentions_me=False), ME, SERVERS, ALANA)
    assert got is not None and got.taint is None


def test_a_bench_talk_message_is_untainted() -> None:
    assert on_bench(1, 7, 4, "hi").taint is None
