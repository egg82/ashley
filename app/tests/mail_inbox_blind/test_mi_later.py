"""A `syncing` answer: the job records the `Later` outcome, which is no check: not a failure, not a pause, not every message
gone, not a baseline."""

import pytest
from ashley.watches.model import Baseline, Failed, Later, Quiet, Woke
from contract.conversations_support import events
from ashley import logs
from mail_inbox_blind_support import (ADDRESS, CONF, OTHER_ADDRESS, FakeResources, World, baseline_of, mail_watch,
                                      msg, pred, run)

HAD = (msg(1), msg(2))


def syncing_world() -> World:
    w = World()
    w.inbox(*HAD)
    w.mailbox.syncing.add(11)
    return w


def test_a_syncing_mailbox_with_no_baseline_yet_is_later_not_a_baseline_of_nothing() -> None:
    w = syncing_world()

    async def go() -> None:
        assert isinstance(await w.check(mail_watch(1, baseline=None)), Later)
    run(go())


def test_a_syncing_mailbox_is_later_not_every_message_gone_whatever_when_and_until_say_of_gone() -> None:
    w = syncing_world()
    gone = ((pred("gone"),),)

    async def go() -> None:
        check = await w.check(mail_watch(1, baseline=baseline_of(*HAD), when=gone, until=gone))
        assert isinstance(check, Later) and not isinstance(check, (Woke, Quiet, Failed, Baseline))
    run(go())


def test_a_syncing_mailbox_is_later_under_the_default_when_too() -> None:
    w = syncing_world()

    async def go() -> None:
        assert isinstance(await w.check(mail_watch(1, baseline=baseline_of(*HAD))), Later)
    run(go())


def test_only_the_syncing_mailbox_is_later_the_other_in_the_same_tick_reads_normally() -> None:
    w = World(resources=FakeResources({ADDRESS: 11, OTHER_ADDRESS: 12}))
    w.inbox(*HAD, connection=11)
    w.inbox(msg(5), connection=12)
    w.mailbox.syncing.add(11)

    async def go() -> None:
        got = await w.tick(mail_watch(1, baseline=None), mail_watch(2, target=OTHER_ADDRESS, baseline=None))
        assert isinstance(got[1], Later) and isinstance(got[2], Baseline) and set(got[2].items) == {"m0005"}
    run(go())


def test_when_the_mailbox_has_filled_in_the_next_read_is_a_normal_one() -> None:
    w = syncing_world()

    async def go() -> None:
        fresh, known = mail_watch(1, baseline=None), mail_watch(2, baseline=baseline_of(*HAD), target=ADDRESS)
        assert isinstance((await w.tick(fresh))[1], Later)
        w.mailbox.syncing.clear()
        got = await w.tick(fresh, known)
        assert isinstance(got[1], Baseline) and set(got[1].items) == {"m0001", "m0002"}
        assert got[2] == Quiet(False)
    run(go())


def test_a_watch_that_has_been_syncing_for_longer_than_fail_after_ticks_is_never_failed_or_paused(
        capsys: pytest.CaptureFixture[str]) -> None:
    w = syncing_world()
    logs.setup()

    async def go() -> None:
        for _ in range(CONF.fail_after + 3):
            check = await w.check(mail_watch(1, baseline=baseline_of(*HAD), failures=CONF.fail_after - 1))
            assert isinstance(check, Later)
    run(go())
    seen = capsys.readouterr()
    ticks = events(seen.out + seen.err, "watches.tick")
    assert len(ticks) == CONF.fail_after + 3
    assert {t["failed"] for t in ticks} == {"0"} and {t["paused"] for t in ticks} == {"0"}
    assert events(seen.out + seen.err, "watches.paused") == [] and events(seen.out + seen.err, "watches.read_failed") == []


def test_a_syncing_read_logs_no_failure_for_the_kind(capsys: pytest.CaptureFixture[str]) -> None:
    w = syncing_world()
    logs.setup()
    run(w.check(mail_watch(1, baseline=None)))
    seen = capsys.readouterr()
    assert events(seen.out + seen.err, "watches.read_failed") == [] and events(seen.out + seen.err, "watches.tick")
