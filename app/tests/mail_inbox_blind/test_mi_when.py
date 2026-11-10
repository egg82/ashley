"""The default `when` ([[new]]): a message read or labelled elsewhere wakes nothing, a new message wakes with that
message as the change."""

from ashley.watches.model import Baseline, Quiet, Woke
from mail_inbox_blind_support import LABEL, World, baseline_of, mail_watch, msg, run

BEFORE = (msg(1, unread=True), msg(2, unread=True))


def watched() -> object:
    return mail_watch(1, baseline=baseline_of(*BEFORE))


def test_a_message_read_elsewhere_wakes_nothing() -> None:
    w = World()
    w.inbox(msg(1, unread=False), msg(2, unread=True))

    async def go() -> None:
        assert await w.check(watched()) == Quiet(False)
    run(go())


def test_a_message_labelled_elsewhere_wakes_nothing() -> None:
    w = World()
    w.inbox(msg(1, labels=(LABEL,)), msg(2, labels=(LABEL, "other")))

    async def go() -> None:
        assert await w.check(watched()) == Quiet(False)
    run(go())


def test_a_message_that_left_the_inbox_wakes_nothing_under_the_default() -> None:
    w = World()
    w.inbox(msg(2))

    async def go() -> None:
        assert await w.check(watched()) == Quiet(False)
    run(go())


def test_a_read_that_changed_nothing_is_quiet() -> None:
    w = World()
    w.inbox(*BEFORE)

    async def go() -> None:
        assert await w.check(watched()) == Quiet(False)
    run(go())


def test_a_new_message_wakes_with_that_message_as_a_new_change() -> None:
    w = World()
    arrived = msg(3, subject="arrived")
    w.inbox(*BEFORE, arrived)

    async def go() -> None:
        check = await w.check(watched())
        assert isinstance(check, Woke) and check.ends is False
        [change] = check.changes
        assert (change.id, change.kind, change.before) == ("m0003", "new", None)
        assert change.after is not None and change.after["subject"] == "arrived"
        assert set(check.items) == {"m0001", "m0002", "m0003"}
    run(go())


def test_a_new_message_wakes_even_when_another_was_read_in_the_same_window() -> None:
    w = World()
    w.inbox(msg(1, unread=False), msg(2), msg(3))

    async def go() -> None:
        check = await w.check(watched())
        assert isinstance(check, Woke) and [c.id for c in check.changes if c.kind == "new"] == ["m0003"]
    run(go())


def test_the_first_read_of_a_full_inbox_is_a_baseline_and_wakes_nothing() -> None:
    w = World()
    w.inbox(*BEFORE)

    async def go() -> None:
        assert isinstance(await w.check(mail_watch(1, baseline=None)), Baseline)
    run(go())
