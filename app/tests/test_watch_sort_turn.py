"""The turn a sort's wake starts: tainted from its first step and told its brief and the sort instruction."""

from dataclasses import replace
from datetime import UTC, datetime

from ashley.channels.audience import owner_alone
from ashley.channels.standing import of as standing_of
from ashley.channels.wake import watch_turn
from ashley.senses.wakes import WatchWake
from ashley.watches.config import CONFIG
from ashley.watches.mail_inbox import SORT_NOTE
from ashley.watches.model import Watch
from ashley.watches.rows import changed_wake

BOX = "me@example.test"
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
BRIEF = "zq-brief-3302"
CONFIG_KIND = CONFIG.kinds["mail_inbox"]


def watch(**over: object) -> Watch:
    base = Watch(9, 1, 2, "mail_inbox", BOX, BOX, None, "ashley", CONFIG_KIND.track, CONFIG_KIND.when, None,
                 ("mail_search", "mail_label"), 60, NOW, "armed", None, 0, 0, 0, None, NOW, NOW, None, None,
                 brief=BRIEF, standing=True)
    return replace(base, **over)


WAKE = WatchWake(1, 2, 9, "changed", changed_wake(1, NOW, False, ()))


def test_the_wake_is_tainted_and_its_note_carries_the_brief_and_the_sort_instruction() -> None:
    turn = watch_turn.inbound(5, watch(), WAKE, False)
    assert turn.taint == "watch"
    assert turn.note is not None
    assert BRIEF in turn.note and SORT_NOTE in turn.note and "without asking" not in turn.note
    assert turn.tools_only == ("mail_search", "mail_label")
    standing = standing_of(turn)
    assert standing is not None and owner_alone(turn) and not standing.agreeing


def test_a_watch_without_a_brief_adds_no_brief_line() -> None:
    turn = watch_turn.inbound(5, watch(brief=None), WAKE, False)
    assert turn.note is not None and "set up" not in turn.note
