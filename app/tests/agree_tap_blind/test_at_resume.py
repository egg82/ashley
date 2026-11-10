"""The tap's turn is checkpointed: a runner that dies after `InFlight.begin` leaves the carry-out to the one that
resumes it, which finishes it once with no model; a change that took effect before the runner died is not run again;
two runners claiming at once run it once."""

from agree_tap_blind_support import REASON_KEY, REASONS, REFUSED_STATUSES, held_calls, world


def test_a_runner_that_dies_right_after_the_checkpoint_leaves_the_carry_out_to_the_next_one(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.die_after_begin = True
        w.tap_dying(w.alana, pid)
        assert w.work_rows() == 1 and w.tools.ran == []
        w.settle()
        assert [c.name for c in w.tools.ran] == [c.tool for c in held_calls()]
        assert w.work_rows() == 0 and not w.pending(w.alana) and w.model.calls == 0


def test_a_resumed_carry_out_is_never_run_a_second_time(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.die_after_begin = True
        w.tap_dying(w.alana, pid)
        w.settle(rounds=4)
        assert len(w.tools.ran) == len(held_calls())
        assert w.tap(w.alana, pid).status_code in REFUSED_STATUSES
        w.settle()
        assert len(w.tools.ran) == len(held_calls())


def test_two_runners_resuming_at_once_carry_it_out_once(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.die_after_begin = True
        w.tap_dying(w.alana, pid)
        w.sweep_together()
        w.settle(rounds=2)
        assert len(w.tools.ran) == len(held_calls()) and w.work_rows() == 0


def test_a_call_that_took_effect_before_the_runner_died_is_not_run_again(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.tools.die_in_call = 1
        w.tap_dying(w.alana, pid)
        assert [c.name for c in w.tools.ran] == ["lamp"]
        w.settle(rounds=4)
        assert [c.name for c in w.tools.ran].count("lamp") == 1
        assert w.work_rows() == 0 and w.model.calls == 0
        assert w.tap(w.alana, pid).status_code in REFUSED_STATUSES


def test_a_resumed_agree_never_asks_a_model_or_changes_who_it_is_for(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.die_after_begin = True
        w.tap_dying(w.alana, pid)
        before = w.checkpoint()
        w.settle()
        assert w.model.calls == 0 and before.inbound.speaker_id == w.alana.id and before.tainted is None


def test_work_left_by_a_refused_tap_never_carries_anything_out_when_resumed(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.age(pid)
        got = w.tap(w.alana, pid)
        assert got.status_code in REFUSED_STATUSES and got.json()[REASON_KEY] == REASONS["expired"]
        w.settle(rounds=3)
        assert w.tools.ran == []
