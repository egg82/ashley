"""The job's log lines: ids and counts, never a target, a label or a field value."""

import pytest
from ashley import logs
from contract.conversations_support import events
from dataclasses import replace

from watch_job_blind_support import CONF, Counts, Hang, Harness, always, ReadFailed, harness, one, run, watch_of

TARGET = "zq-target-6619"
LABEL = "zq-label-2284"
VALUE = "zq-value-5530"


def ticked(h: Harness, capsys: pytest.CaptureFixture[str]) -> str:
    logs.setup()
    run(h.tick())
    seen = capsys.readouterr()
    return seen.out + seen.err


def mixed() -> list[object]:
    return [
        watch_of(1, target=TARGET, label=LABEL, baseline=None),                                      # baseline
        watch_of(2, target="b", baseline=one("b", "working", 1), person_id=8),                         # quiet
        watch_of(3, target="c", baseline=one("c", "working", 1), person_id=9),                         # woke
        watch_of(5, target="e", baseline=one("e", "done", 1), person_id=11, failures=0),               # failed
        watch_of(6, target="f", baseline=one("f", "done", 1), person_id=12, failures=2),               # paused
        watch_of(7, target="g", baseline=one("g", "done", 1), person_id=13, state="paused", failures=3)]  # resumed


def world() -> dict[int, object]:
    return {1: one(TARGET, "done", 2), 2: one("b", "working", 1), 3: {"c": {"status": "done", "seq": 2, "note": VALUE}},
            5: ReadFailed("unreachable"), 6: ReadFailed("unreachable"), 7: one("g", "done", 1)}


def test_the_tick_line_counts_every_outcome(capsys: pytest.CaptureFixture[str]) -> None:
    h = harness(mixed(), world())
    h.store.counts = Counts(2, 3)
    out = ticked(h, capsys)
    [line] = events(out, "watches.tick")
    got = {k: line[k] for k in ("expired", "pruned", "due", "baselines", "quiet", "woke", "failed", "paused", "resumed")}
    assert got == {"expired": "2", "pruned": "3", "due": "6", "baselines": "1", "quiet": "2", "woke": "1", "failed": "2",
                   "paused": "1", "resumed": "1"}
    assert int(line["duration_ms"]) >= 0


def test_a_failed_group_logs_its_kind_reason_and_how_many_watches(capsys: pytest.CaptureFixture[str]) -> None:
    h = harness([watch_of(1, target="a"), watch_of(2, target="b")], {1: ReadFailed("refused"), 2: ReadFailed("refused")})
    [line] = events(ticked(h, capsys), "watches.read_failed")
    assert (line["kind"], line["reason"], line["watches"]) == ("claude_session", "refused", "2")


def test_nothing_in_the_logs_names_a_target_a_label_or_a_value(capsys: pytest.CaptureFixture[str]) -> None:
    h = harness(mixed(), world())
    out = ticked(h, capsys)
    assert out and TARGET not in out and LABEL not in out and VALUE not in out


def test_a_raising_kind_is_logged_as_failed_with_no_traceback_text_of_the_read(
        capsys: pytest.CaptureFixture[str]) -> None:
    h = harness([watch_of(1, target=TARGET)], {})
    h.kind.script = always(RuntimeError("boom"))
    out = ticked(h, capsys)
    [line] = events(out, "watches.tick")
    assert line["failed"] == "1" and TARGET not in out


def test_a_hung_read_is_a_failed_watch_in_the_tick_line(capsys: pytest.CaptureFixture[str]) -> None:
    h = harness([watch_of(1)], {}, replace(CONF, read_timeout_s=0.05))
    h.kind.script = always(Hang())
    [line] = events(ticked(h, capsys), "watches.tick")
    assert line["failed"] == "1"


def test_a_closed_handoff_session_counts_as_ended(capsys: pytest.CaptureFixture[str]) -> None:
    h = harness([watch_of(1, baseline=one("a", "done", 1), target="a")], {1: {}})
    [line] = events(ticked(h, capsys), "watches.tick")
    assert line["ended"] == "1" and line["woke"] == "0"


def test_wj_the_woke_line_carries_no_target_label_or_value(capsys: pytest.CaptureFixture[str]) -> None:
    watch = watch_of(1, target=TARGET, label=LABEL, baseline=one(TARGET, "working", 1))
    h = harness([watch], {1: {TARGET: {"status": "done", "seq": 2, "note": VALUE}}})
    out = ticked(h, capsys)
    [line] = events(out, "watches.woke")
    assert line["watch"] == "1" and TARGET not in out and LABEL not in out and VALUE not in out
