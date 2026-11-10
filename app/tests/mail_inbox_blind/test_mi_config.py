"""What the kind is: registered as `mail_inbox`, outside, tracking four fields, `[[new]]` by default; and a woken turn of
it starts tainted while one of a kind that is not outside does not."""

from datetime import UTC, datetime
from typing import Any

from ashley.channels.wake.watch_turn import inbound
from ashley.criteria import condition
from ashley.criteria.record import Change
from ashley.senses.wakes import WatchWake
from ashley.watches.kinds import NullKind
from ashley.watches.rows import changed_wake
from ashley.watches.registry import KINDS
from mail_inbox_blind_support import ADDRESS, CONFIG, SENDER, SUBJECT, TRACK, MailInbox, mail_watch

NEW = condition.from_json([[{"kind": "new", "negate": False}]])


def test_the_kind_is_registered_under_its_name_and_is_not_the_null_kind() -> None:
    kind = KINDS.get("mail_inbox")
    assert isinstance(kind, MailInbox) and not isinstance(kind, NullKind) and kind.name == "mail_inbox"


def test_the_kind_is_outside_in_the_class_and_in_the_data() -> None:
    assert KINDS.get("mail_inbox").outside is True
    assert CONFIG.kinds["mail_inbox"].outside is True


def test_the_kind_tracks_from_subject_unread_and_labels_and_nothing_else() -> None:
    assert set(CONFIG.kinds["mail_inbox"].track) == set(TRACK)


def test_the_default_when_is_a_new_message_alone() -> None:
    assert CONFIG.kinds["mail_inbox"].when == NEW


def test_the_kind_has_a_positive_interval() -> None:
    assert CONFIG.kinds["mail_inbox"].interval_s > 0


def wake_of(kind: str) -> tuple[WatchWake, Any]:
    after = {"from": SENDER, "subject": SUBJECT, "unread": True, "labels": ""}
    stored = changed_wake(1, datetime(2026, 11, 1, tzinfo=UTC), False, (Change("m1", "new", None, after),))
    return WatchWake(1, 7, 1, "changed", stored), mail_watch(1, kind=kind, target=ADDRESS)


def test_the_turn_a_mail_inbox_wake_starts_is_tainted_by_the_watch() -> None:
    wake, watch = wake_of("mail_inbox")
    for on_bench in (False, True):
        assert inbound(1, watch, wake, on_bench).taint == "watch"


def test_a_wake_of_a_kind_that_is_not_outside_starts_untainted() -> None:
    wake, watch = wake_of("claude_session")
    assert CONFIG.kinds["claude_session"].outside is False
    assert inbound(1, watch, wake, False).taint is None
