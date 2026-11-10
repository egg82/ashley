"""Contracts 16, 20 and 21 (and the kind of watch, I9): one watch per group; the woken turn is the existing `watch_turn`,
on the bench, tainted `watch`; it fires once the whole group has settled, with every job's result and nothing of any
transcript; a job that needs the person (`blocked`) wakes her at once."""

from typing import Any

import pytest
from ashley.errands.bench_job_model import Ending, Worker
from bjb_support import (MARK_TITLE, World, calls_of, outcome, payload, scenario, settle_wakes, spec, wake_count,
                         watch_kind_outside, watch_tick, woken, woken_text)
from ashley.watches.config import CONFIG

SUMMARY = "SUMMARY-MARK-hh88"
TRANSCRIPT = "TRANSCRIPT-MARK-ii99"


async def armed_group(w: World, *specs: dict[str, object], can_code: bool = False) -> list[dict[str, Any]]:
    jobs = payload(await w.hand_off(*specs, can_code=can_code))["jobs"]
    await watch_tick(w)
    assert wake_count(w.url) == 0
    return list(jobs)


async def finish(w: World, worker: Worker, state: Ending, **kw: Any) -> int:
    job = await w.claimed(worker)
    await w.jobs.finish(job.id, job.attempts, outcome(state, **kw))
    return int(job.id)


def test_i9_the_kind_is_outside_and_tracks_settled_blocked_and_waiting() -> None:
    assert CONFIG.kinds["bench_job"].outside is True
    assert tuple(CONFIG.kinds["bench_job"].track) == ("settled", "blocked", "waiting")
    assert watch_kind_outside() is True


@pytest.mark.parametrize(("state", "extra"), [("done", {}), ("failed", {"reason": "bridge_unavailable"}),
                                              ("timed_out", {"reason": "deadline"})])
def test_c16_a_settled_job_wakes_one_turn_on_its_bench_tainted_watch_with_its_result(
        db_url: str, state: Ending, extra: dict[str, str]) -> None:
    async def body(w: World) -> None:
        note = await w.piece("note", "made-by-worker", "x")
        await armed_group(w, spec(title=MARK_TITLE))
        await finish(w, "agent", state, summary=SUMMARY, outputs=(note,), **extra)
        await watch_tick(w)
        assert wake_count(w.url) == 1
        (turn,) = await woken(w)
        text = woken_text(turn)
        assert turn.thread == f"bench:{w.bench}" and turn.bench_id == w.bench and turn.unprompted is True
        assert turn.taint == "watch" and turn.speaker_id == w.owner.person_id
        for expected in (MARK_TITLE, state, SUMMARY, str(note), *extra.values()):
            assert expected in text, expected
        settle_wakes(w.url)
        await watch_tick(w)
        await watch_tick(w)
        assert wake_count(w.url) == 1

    scenario(db_url, body)


def test_c20_a_group_of_three_wakes_exactly_once_after_the_last_settles_with_all_three_results(db_url: str) -> None:
    async def body(w: World) -> None:
        a, b, c = [await w.piece("note", f"out{i}", "x") for i in range(3)]
        await armed_group(w, spec(title="TITLE-ONE-aa"), spec(title="TITLE-TWO-bb"), spec(title="TITLE-THREE-cc"))
        await finish(w, "agent", "done", summary="SUMMARY-ONE-aa", outputs=(a,))
        await watch_tick(w)
        assert wake_count(w.url) == 0
        await finish(w, "agent", "failed", reason="attempts", summary="SUMMARY-TWO-bb")
        await watch_tick(w)
        assert wake_count(w.url) == 0
        await finish(w, "agent", "timed_out", reason="deadline", summary="SUMMARY-THREE-cc", outputs=(b, c))
        await watch_tick(w)
        assert wake_count(w.url) == 1
        (turn,) = await woken(w)
        text = woken_text(turn)
        for mark in ("TITLE-ONE-aa", "TITLE-TWO-bb", "TITLE-THREE-cc", "SUMMARY-ONE-aa", "SUMMARY-TWO-bb",
                     "SUMMARY-THREE-cc", "attempts", "deadline", "failed", "timed_out", "done"):
            assert mark in text, mark
        settle_wakes(w.url)
        await watch_tick(w)
        assert wake_count(w.url) == 1

    scenario(db_url, body)


def test_c20_two_groups_wake_independently(db_url: str) -> None:
    async def body(w: World) -> None:
        await armed_group(w, spec(title="GROUP-A-aa"))
        second = payload(await w.hand_off(spec(title="GROUP-B-bb")))["jobs"]
        assert second
        await watch_tick(w)
        await finish(w, "agent", "done", summary="first done")
        await watch_tick(w)
        assert wake_count(w.url) == 1
        (turn,) = await woken(w)
        assert "GROUP-A-aa" in woken_text(turn) and "GROUP-B-bb" not in woken_text(turn)

    scenario(db_url, body)


def test_c20_a_group_with_a_cancelled_job_settles_when_the_rest_are_final(db_url: str) -> None:
    async def body(w: World) -> None:
        first, second = await armed_group(w, spec(title="cancelled-one"), spec(title="finished-two"))
        await w.jobs.cancel(w.owner.household_id, w.owner.person_id, int(first["job"]))
        await watch_tick(w)
        assert wake_count(w.url) == 0
        await finish(w, "agent", "done", summary=SUMMARY)
        await watch_tick(w)
        assert wake_count(w.url) == 1 and second

    scenario(db_url, body)


def test_c16_a_blocked_claude_code_job_wakes_her_at_once_and_the_settling_wakes_her_again(db_url: str) -> None:
    async def body(w: World) -> None:
        await armed_group(w, spec("claude_code", title="NEEDS-YOU-jj"), spec("agent", title="other"), can_code=True)
        code = await w.claimed("claude_code")
        await w.jobs.started(code.id, code.attempts, "sess-1")
        await w.jobs.state(code.id, code.attempts, "blocked")
        await watch_tick(w)
        assert wake_count(w.url) == 1
        (turn,) = await woken(w)
        assert "NEEDS-YOU-jj" in woken_text(turn) and "blocked" in woken_text(turn)
        settle_wakes(w.url)
        await w.jobs.state(code.id, code.attempts, "running")
        await finish(w, "agent", "done", summary="agent finished")
        await w.jobs.finish(code.id, code.attempts, outcome("done", summary=SUMMARY))
        await watch_tick(w)
        assert wake_count(w.url) == 2

    scenario(db_url, body)


def test_c16_the_woken_note_carries_the_summary_and_never_the_workers_transcript(db_url: str) -> None:
    async def body(w: World) -> None:
        await armed_group(w, spec(title="Gate"))
        w.model.script = [calls_of(("bench_add", {"kind": "note", "title": TRANSCRIPT, "body": TRANSCRIPT})),
                          {"done": True, "summary": SUMMARY, "pieces": []}]
        await w.ticks(5)
        await watch_tick(w)
        (turn,) = await woken(w)
        text = woken_text(turn)
        assert SUMMARY in text and TRANSCRIPT not in text

    scenario(db_url, body)


def test_c16_a_claude_code_finish_wakes_with_the_result_md_summary_and_no_session_screen(db_url: str) -> None:
    async def body(w: World) -> None:
        await armed_group(w, spec("claude_code", title="Code"), can_code=True)
        await w.ticks(3)
        sid = next(iter(w.bridge.sessions_))
        w.bridge.out[sid] = {"RESULT.md": SUMMARY.encode(), "extra.txt": b"x\n"}
        w.bridge.settle(sid, "done")
        await w.ticks(4)
        await watch_tick(w)
        (turn,) = await woken(w)
        assert SUMMARY in woken_text(turn) and w.bridge.named("read") == []

    scenario(db_url, body)
