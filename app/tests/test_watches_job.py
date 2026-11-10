"""One job tick against a fake store: grouping, reads, judging, recording, and what it logs."""

import asyncio
import logging
from collections import Counter
from dataclasses import replace

import pytest
from ashley import services
from ashley.logs import Logfmt
from ashley.watches import job
from ashley.watches.config import CONFIG, WatchesConfig
from ashley.watches.kinds import Registry
from ashley.watches.model import Baseline, Counts, Failed, Quiet, ReadFailed, Woke
from ashley.watches.watches import Watches
from watch_job_support import FakeWatches, ScriptedKind, session, watch


def tick(store: FakeWatches, kind: ScriptedKind, config: WatchesConfig = CONFIG) -> Counter[str]:
    services.register(Watches, store)
    return asyncio.run(job.tick(config, Registry([kind])))


def lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [Logfmt().format(r) for r in caplog.records]


def test_each_watch_is_judged_and_recorded_at_its_version(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    store = FakeWatches(due_rows=(watch(1), watch(2, session("working", 1, "s2"), target="s2", version=3),
                                  watch(3, session("working", 1, "s3"), target="s3", version=1)))
    kind = ScriptedKind(reads={1: session("idle", 1), 2: session("done", 2, "s2"), 3: session("working", 1, "s3")})
    counts = tick(store, kind)
    assert [(i, v, type(c)) for i, v, c in store.recorded] == [(1, 0, Baseline), (2, 3, Woke), (3, 1, Quiet)]
    assert (counts["baselines"], counts["woke"], counts["quiet"], counts["due"]) == (1, 1, 1, 3)
    assert any("event=watches.woke" in line and "series=1" in line and "changed=1" in line for line in lines(caplog))


def test_one_read_per_kind_household_and_person() -> None:
    store = FakeWatches(due_rows=(watch(1), watch(2, target="s2"), watch(3, person=8), watch(4, household=2)))
    kind = ScriptedKind(reads={})
    tick(store, kind)
    assert sorted(kind.groups) == [(1, 2), (3,), (4,)]


def test_expire_runs_first_and_due_is_bounded_by_the_batch() -> None:
    store = FakeWatches(due_rows=tuple(watch(i, target=f"s{i}") for i in range(1, 6)))
    tick(store, ScriptedKind(), replace(CONFIG, batch=2))
    assert store.calls == ["expire", "due"] and len(store.recorded) == 2


def test_a_kind_that_raises_fails_every_watch_in_its_group_without_its_message(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    store = FakeWatches(due_rows=(watch(1), watch(2, target="s2")))
    tick(store, ScriptedKind(boom=True))
    assert [c for _, _, c in store.recorded] == [Failed("unreachable")] * 2
    assert "secret-looking" not in "\n".join(lines(caplog))
    assert any("event=watches.read_failed" in line and "watches=2" in line for line in lines(caplog))


def test_a_kind_that_outlasts_the_timeout_fails_its_group() -> None:
    store = FakeWatches(due_rows=(watch(1),))
    tick(store, ScriptedKind(hang=True), replace(CONFIG, read_timeout_s=0.05))
    assert [c for _, _, c in store.recorded] == [Failed("unreachable")]


def test_an_unknown_kind_fails_unknown_kind_and_a_missing_read_is_bad_result() -> None:
    store = FakeWatches(due_rows=(watch(1, kind="mystery"), watch(2, target="s2")))
    tick(store, ScriptedKind(reads={}))
    assert [c for _, _, c in store.recorded] == [Failed("unknown_kind"), Failed("bad_result")]


def test_the_nth_failure_pauses_and_a_good_read_resumes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    last = watch(1, failures=CONFIG.fail_after - 1)
    paused = watch(2, session("working", 1, "s2"), target="s2", state="paused", failures=CONFIG.fail_after)
    store = FakeWatches(due_rows=(last, paused))
    counts = tick(store, ScriptedKind(reads={1: ReadFailed("refused"), 2: session("working", 1, "s2")}))
    assert (counts["paused"], counts["resumed"], counts["failed"], counts["quiet"]) == (1, 1, 1, 1)
    out = "\n".join(lines(caplog))
    assert "event=watches.paused" in out and "event=watches.resumed" in out


def test_a_record_another_holder_won_is_counted_lost_and_nothing_else() -> None:
    store = FakeWatches(due_rows=(watch(1),), accept=False)
    counts = tick(store, ScriptedKind(reads={1: session("done", 1)}))
    assert counts["lost"] == 1 and counts["baselines"] == 0


def test_an_ending_check_is_counted_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    from ashley.criteria import condition
    caplog.set_level(logging.INFO)
    gone = condition.from_json([[{"kind": "gone", "negate": False}]])
    store = FakeWatches(due_rows=(watch(1, session("working", 1), until=gone),))
    counts = tick(store, ScriptedKind(reads={1: {}}))
    assert counts["ended"] == 1 and any("event=watches.ended" in line for line in lines(caplog))


def test_a_tick_with_nothing_due_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    tick(FakeWatches(), ScriptedKind())
    assert lines(caplog) == []


def test_the_tick_log_carries_no_target_or_label(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    store = FakeWatches(due_rows=(watch(1, session("working", 1), target="the-target-id"),), expired=Counts(1, 0))
    tick(store, ScriptedKind(reads={1: session("done", 2, "the-target-id")}))
    out = "\n".join(lines(caplog))
    assert "event=watches.tick" in out and "the-target-id" not in out and "label" not in out


def test_run_logs_unavailable_once_per_run_of_failed_ticks(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    services.register(Watches, FakeWatches(down=True))
    n = 0

    async def sleep(_: float) -> None:
        nonlocal n
        n += 1
        if n == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(job.run(CONFIG, Registry([]), sleep))
    assert sum("event=watches.unavailable" in line for line in lines(caplog)) == 1
