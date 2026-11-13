"""Directed tests for what the blind suite's planted mutants left alive. Written with the implementation in view, each
names the mutant it kills in `MUTANTS.txt`."""

import ast
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley import services
from ashley.channels.bench_job import NAME
from ashley.channels.bench_job import runner as runner_module
from ashley.errands.bench_job_model import Job
from ashley.inference.model import Prompt
from ashley.errands.bench_jobs import BenchJobs, JobsUnavailable
from ashley.tools import bench_job_piece
from ashley.workshop.commands import Add, Edit
from ashley.workshop.model import HER, By, Text
from ashley.workshop.workshop import Workshop
from bjb_bridge_support import Bridge, build_bridge, put, session_dir
from bjb_support import (ACCESS, HANG, MARK_TITLE, ROOT, World, call, cfg, finished, job_count, job_pieces, limit, new_job,
                         outcome, payload, reason, row, scenario, spec, state_of, watch_rows)
from test_bjb_c11_c13_session import claude_job, only_session, step

APP = Path(__file__).resolve().parent.parent.parent


def test_m051_a_group_is_recorded_whole_or_not_at_all(db_url: str) -> None:
    async def body(w: World) -> None:
        bad: Any = replace(new_job(w, title="c"), **{"title": " "})
        with pytest.raises(JobsUnavailable):
            await w.jobs.start_group((new_job(w, title="a"), new_job(w, title="b"), bad))
        assert job_count(w.url) == 0

    scenario(db_url, body)


def test_m012_a_bench_that_is_not_theirs_answers_unavailable_before_any_count(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(limit("max_running", "agent")):
            await w.started(title=f"t{i}")
        assert reason(await w.hand_off(spec(), bench=w.foreign_bench)) == "unavailable"
        assert job_count(w.url) == limit("max_running", "agent")

    scenario(db_url, body)


def test_m039_a_job_is_given_up_after_exactly_max_attempts_claims(db_url: str) -> None:
    async def body(w: World) -> None:
        job_id = await w.started()
        claims = 0
        for _ in range(limit("max_attempts") + 2):
            job = await w.jobs.claim("agent", cfg().claim_s)
            if job is None:
                break
            claims += 1
            await w.jobs.sweep(cfg().claim_s, datetime.now(UTC) + timedelta(seconds=cfg().claim_s * 2))
        assert claims == limit("max_attempts") and state_of(w.url, job_id) == "failed"

    scenario(db_url, body)


def test_x12_sweep_judges_a_lapse_against_the_clock_it_is_given(db_url: str) -> None:
    async def body(w: World) -> None:
        job_id = await w.started()
        await w.claimed()
        assert (await w.jobs.sweep(cfg().claim_s, None)).retaken == 0 and state_of(w.url, job_id) == "running"
        later = datetime.now(UTC) + timedelta(seconds=cfg().claim_s * 2)
        assert (await w.jobs.sweep(cfg().claim_s, later)).retaken == 1 and state_of(w.url, job_id) == "due"

    scenario(db_url, body)


def test_m073_the_title_reaches_neither_the_prompt_nor_the_upload(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started("claude_code", title=MARK_TITLE)
        job = await w.claimed("claude_code")
        await step(w, job)
        assert not any(MARK_TITLE in p for ps in w.bridge.prompts.values() for p in ps)
        assert not any(MARK_TITLE in name for name in w.bridge.refused_file_names())

    scenario(db_url, body)


def test_m097_a_job_finishing_does_not_touch_its_siblings_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        one, two = payload(await w.hand_off(spec(title="one", brief="JOB-ONE"), spec(title="two", brief="JOB-TWO")))["jobs"]
        release = asyncio.Event()

        async def wait(_: Prompt) -> dict[str, Any]:
            await release.wait()
            return finished("one done")

        w.model.routed = {"JOB-ONE": [wait], "JOB-TWO": [HANG]}
        await w.ticks(2)
        before = (await w.pieces())[two["piece"]].version
        release.set()
        await w.ticks(3)
        assert state_of(w.url, one["job"]) == "done" and state_of(w.url, two["job"]) == "running"
        assert (await w.pieces())[two["piece"]].version == before

    scenario(db_url, body)


def test_m099_the_runner_runs_under_the_bench_jobs_lease() -> None:
    tree = ast.parse((APP / "ashley" / "wiring_singletons.py").read_text())
    leased = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
              and c.func.attr == "run" and len(c.args) == 2 and isinstance(c.args[0], ast.Attribute)
              and c.args[0].attr == "NAME" and "BenchJobRunner" in ast.dump(c.args[1])]
    assert len(leased) == 1 and NAME == "bench_jobs"


def test_m109_the_watch_is_the_groups_not_a_jobs(db_url: str) -> None:
    async def body(w: World) -> None:
        first = payload(await w.hand_off(spec(title="a"), spec(title="b")))["jobs"]
        for _ in first:
            job = await w.claimed()
            await w.jobs.finish(job.id, job.attempts, outcome("done", summary="s"))
        made = payload(await w.hand_off(spec(title="c")))
        job_id = made["jobs"][0]["job"]
        assert made["group"] != job_id
        assert watch_rows(w.url)[-1][2] == str(made["group"])

    scenario(db_url, body)


async def job_piece_of(w: World) -> Any:
    payload(await w.hand_off(spec()))
    return job_pieces(await w.pieces())[0]


def test_m117_m118_neither_she_nor_the_person_edits_a_job_piece_whatever_its_body(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece_of(w)
        for by in (By(w.owner.person_id), HER):
            got = await services.get(Workshop).apply(w.owner, w.bench, Edit(by, piece.id, piece.version,
                                                                             Text(piece.text.title, piece.text.body)))
            assert got.outcome == "bad_body", by

    scenario(db_url, body)


def test_m119_neither_she_nor_the_person_adds_a_job_piece_whatever_its_body(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece_of(w)
        for by in (By(w.owner.person_id), HER):
            got = await services.get(Workshop).apply(w.owner, w.bench, Add(by, "job", Text("x", piece.text.body), "small"))
            assert got.outcome == "bad_body", by

    scenario(db_url, body)


def test_x07_a_boolean_is_not_a_job_id(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await w.started()
        got = await w.tools().call(call("bench_job_cancel", job=True))
        assert reason(got) == "bad_arguments" and state_of(w.url, job) == "due"

    scenario(db_url, body)


def test_x08_the_piece_shows_the_job_as_stored_now_not_as_the_caller_saw_it(db_url: str) -> None:
    async def body(w: World) -> None:
        made = payload(await w.hand_off(spec()))["jobs"][0]
        stale = await w.claimed()
        await w.jobs.finish(stale.id, stale.attempts, outcome("done", summary="s"))
        await bench_job_piece.show(w.owner, stale)
        shown = json_state((await w.pieces())[made["piece"]])
        assert shown == "done"

    scenario(db_url, body)


def json_state(piece: Any) -> str:
    import json
    return str(json.loads(piece.text.body)["state"])


def test_x09_a_finishing_agent_task_is_not_cancelled_while_it_writes_its_piece(
        db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(w: World) -> None:
        made = payload(await w.hand_off(spec()))["jobs"][0]
        w.model.script = [finished("done")]
        real = runner_module.settle.shown
        writing, written = asyncio.Event(), asyncio.Event()

        async def held(job_id: int, household_id: int, person_id: int) -> Job | None:
            got = await services.get(BenchJobs).get(household_id, person_id, job_id)
            if got is not None and got.final and not writing.is_set():
                writing.set()
                await asyncio.wait_for(written.wait(), 5)
            return await real(job_id, household_id, person_id)

        monkeypatch.setattr(runner_module.settle, "shown", held)
        runner = w.runner()
        await runner.tick()
        await asyncio.wait_for(writing.wait(), 5)
        await runner.tick()  # the job is final, so no longer active, while its task still writes the piece
        await runner.tick()
        written.set()
        for _ in range(250):
            if json_state((await w.pieces())[made["piece"]]) == "done":
                break
            await asyncio.sleep(0.02)
        assert json_state((await w.pieces())[made["piece"]]) == "done"

    scenario(db_url, body)


@pytest.mark.parametrize(("moved", "prompts"), [(True, 0), (False, 1)])
def test_x10_a_retaken_session_is_prompted_only_when_its_state_count_has_not_moved(
        db_url: str, moved: bool, prompts: int) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        made = await w.bridge.start(ACCESS, f"{ROOT}/ashley-jobs/j{job.id}", f"job-{job.id}", None)
        await w.jobs.started(job.id, job.attempts, made.id, made.seq)
        if moved:
            w.bridge.settle(made.id, "working")
        w.bridge.calls.clear()
        assert await step(w, job) is None
        assert len(w.bridge.named("prompt")) == prompts and row(w.url, job.id)["prompted_at"] is not None
        assert only_session(w) == made.id

    scenario(db_url, body)


@pytest.fixture
def bridge(tmp_path: Path, pki: Any) -> Bridge:
    return build_bridge(tmp_path, pki)


@pytest.mark.parametrize("name", ["a/b", "a/../b", "x\x00y", "dir/", "/abs"])
def test_m126_m129_a_slash_or_a_nul_in_a_name_is_bad_request(bridge: Bridge, name: str) -> None:
    sid, where = session_dir(bridge)
    got = put(bridge, sid, name, b"x")
    assert (got.status, got.body) == (400, {"error": "bad_request"})
    assert not (where / "in").exists() or list((where / "in").iterdir()) == []

