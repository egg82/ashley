"""The bench jobs runner and the group's watch over a real database, a scripted model and an in-memory bridge: agent
jobs run under the runner's tick; a job finishing first changes only its own piece and wakes nothing; the group's one
watch wakes once when the last job ends, carrying every result and no transcript; a blocked Claude Code job wakes at
once; a removed piece cancels its job; a past-deadline agent ends `timed_out`; a cancelled session is closed; a lapsed
claim is retaken by the next holder."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ashley import services
from ashley.channels.bench_job import BenchJobRunner
from ashley.errands.bench_jobs import BenchJobs, Job
from ashley.errands.jobs_config import CONFIG
from ashley.tools import bench_agent
from ashley.tools.bench_job_cancel import cancel
from ashley.watches import job as watches_job
from ashley.watches.registry import KINDS
from ashley.watches.watches import Watches
from ashley.workshop.commands import Remove
from ashley.workshop.model import RUNNER
from ashley.workshop.workshop import Workshop
from bench_jobs_support import Jobs, db_url as db_url, jobs_world, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from test_bench_hand_off import hand_off, job as spec

RESULT = bench_agent.JobResult
ONE_AGENT = replace(CONFIG, max_running={"agent": 1, "claude_code": 3})


async def group(w: Jobs, workers: Sequence[str]) -> tuple[int, list[Job]]:
    got = json.loads((await hand_off(w, [spec(x, title=f"T{i}") for i, x in enumerate(workers)])).content)
    return got["group"], list(await services.get(BenchJobs).group(w.s.household, w.s.person, got["group"]))


async def watch_tick(w: Jobs) -> None:
    async with w.run.database.connection() as conn:
        await conn.execute("UPDATE watches SET next_check_at = now() - interval '1 second'")
    await watches_job.tick()


def wakes(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM wakes WHERE kind = 'watch'"))


async def state(w: Jobs, job: Job) -> str:
    view = await services.get(Workshop).read(w.owner, w.s.bench)
    return str(json.loads(next(p for p in view.pieces if p.id == job.piece_id).text.body)["state"])


async def fresh(w: Jobs, job: Job) -> Job:
    got = await services.get(BenchJobs).get(w.s.household, w.s.person, job.id)
    assert got is not None
    return got


def test_the_first_job_to_end_changes_only_its_piece_and_the_last_wakes_her_once_with_every_result(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            gid, (a, b) = await group(w, ["agent", "agent"])
            w.model.script = [RESULT(done=True, summary="alpha result", pieces=[]),
                              RESULT(done=False, summary="beta result", pieces=[])]
            runner = BenchJobRunner(ONE_AGENT)
            await runner.tick()
            await runner.idle()
            await watch_tick(w)
            assert (await state(w, a), await state(w, b), wakes(db_url)) == ("done", "due", 0)
            await runner.tick()
            await runner.idle()
            await watch_tick(w)
            assert (await state(w, a), await state(w, b), wakes(db_url)) == ("done", "failed", 1)
            await watch_tick(w)
            assert wakes(db_url) == 1
            (watch,) = [x for x in [await services.get(Watches).get(1)] if x is not None] or [None]
            assert watch is not None and watch.state == "ended"
            detail = json.loads(await KINDS.get("bench_job").detail(watch))
            assert [(d["title"], d["state"], d["summary"]) for d in detail] == [
                ("T0", "done", "alpha result"), ("T1", "failed", "beta result")]
            assert all(set(d) == {"job", "title", "worker", "state", "reason", "summary", "outputs"} for d in detail)
            assert gid == a.group_id
    run(go())


def test_a_blocked_session_wakes_her_at_once_and_the_group_wakes_again_when_it_settles(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            _, (job,) = await group(w, ["claude_code"])
            runner = BenchJobRunner()
            await runner.tick()
            (sid,) = w.bridge.listed
            assert await state(w, job) == "running"
            w.bridge.state(sid, "blocked", 6)
            await runner.tick()
            await watch_tick(w)
            assert (await state(w, job), wakes(db_url)) == ("blocked", 1)
            async with w.run.database.connection() as conn:
                await conn.execute("UPDATE wakes SET settled_at = now(), outcome = 'turn' WHERE settled_at IS NULL")
            w.bridge.files[sid] = {"RESULT.md": b"finished"}
            w.bridge.state(sid, "done", 7)
            await runner.tick()
            await watch_tick(w)
            assert (await state(w, job), wakes(db_url)) == ("done", 2)
            assert (await fresh(w, job)).summary == "finished" and w.bridge.listed
    run(go())


def test_a_finished_job_s_session_is_closed_once_its_outputs_are_collected(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            _, (job,) = await group(w, ["claude_code"])
            runner = BenchJobRunner()
            await runner.tick()
            (sid,) = w.bridge.listed
            w.bridge.files[sid] = {"RESULT.md": b"finished", "a.txt": b"made"}
            w.bridge.state(sid, "done", 7)
            await runner.tick()
            ended = await fresh(w, job)
            assert ended.state == "done" and len(ended.outputs) == 1 and ("close", sid, "") not in w.bridge.log
            await runner.tick()
            await runner.tick()
            assert w.bridge.listed == {} and w.bridge.log.count(("close", sid, "")) == 1
            assert (await fresh(w, job)).outputs == ended.outputs
    run(go())


def test_a_timed_out_or_failed_job_s_session_is_closed_too_and_a_silent_bridge_is_asked_again(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            _, (late, lost) = await group(w, ["claude_code", "claude_code"])
            runner = BenchJobRunner()
            await runner.tick()
            sid_late, sid_lost = (await fresh(w, late)).session_id, (await fresh(w, lost)).session_id
            assert sid_late is not None and sid_lost is not None and len(w.bridge.listed) == 2
            async with w.run.database.connection() as conn:
                await conn.execute("UPDATE bench_jobs SET deadline_at = now() - interval '1 minute' WHERE id = %s", (late.id,))
            w.bridge.listed.pop(sid_lost)
            await runner.tick()
            assert (await fresh(w, late)).state == "timed_out" and (await fresh(w, lost)).state == "failed"
            w.bridge.down = True
            await runner.tick()
            assert list(w.bridge.listed) == [sid_late] and len(await services.get(BenchJobs).due_closes()) == 2
            w.bridge.down = False
            await runner.tick()
            assert w.bridge.listed == {} and await services.get(BenchJobs).due_closes() == ()
            assert w.bridge.log.count(("close", sid_late, "")) == 1
    run(go())


def test_a_job_handed_off_to_a_silent_machine_waits_then_starts_and_wakes_her(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            w.bridge.down = True
            _, (job,) = await group(w, ["claude_code"])
            assert (job.state, await state(w, job)) == ("waiting", "waiting")
            runner = BenchJobRunner()
            await runner.tick()
            await runner.tick()
            await watch_tick(w)
            assert (await state(w, job), wakes(db_url), w.bridge.listed) == ("waiting", 0, {})
            w.bridge.down = False
            await runner.tick()
            assert (await fresh(w, job)).state == "due"
            await runner.tick()
            await watch_tick(w)
            assert (await state(w, job), wakes(db_url)) == ("running", 1)
            assert len(w.bridge.listed) == 1 and len(w.bridge.prompts) == 1
    run(go())


def test_a_waiting_job_past_its_deadline_fails_and_wakes_her_once(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            w.bridge.down = True
            _, (job,) = await group(w, ["claude_code"])
            runner = BenchJobRunner()
            await runner.tick()
            async with w.run.database.connection() as conn:
                await conn.execute("UPDATE bench_jobs SET deadline_at = now() - interval '1 minute'")
            await runner.tick()
            await watch_tick(w)
            ended = await fresh(w, job)
            assert (ended.state, ended.reason) == ("failed", "herdr_unavailable") and wakes(db_url) == 1
            assert await state(w, job) == "failed" and w.bridge.log == []
    run(go())


def test_a_waiting_job_that_gives_up_wakes_her_while_the_rest_of_the_group_goes_on(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            w.bridge.down = True
            w.model.hang = True
            _, (code, agent) = await group(w, ["claude_code", "agent"])
            await watch_tick(w)
            runner = BenchJobRunner(ONE_AGENT)
            async with w.run.database.connection() as conn:
                await conn.execute("UPDATE bench_jobs SET deadline_at = now() - interval '1 minute' "
                                   "WHERE worker = 'claude_code'")
            await runner.tick()
            await watch_tick(w)
            assert (await fresh(w, code)).state == "failed" and wakes(db_url) == 1
            assert (await fresh(w, agent)).state == "running"
    run(go())


def test_a_removed_job_piece_cancels_its_job_before_it_runs(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            _, (job,) = await group(w, ["agent"])
            await services.get(Workshop).apply(w.owner, w.s.bench, Remove(RUNNER, job.piece_id))
            await BenchJobRunner(ONE_AGENT).tick()
            assert (await fresh(w, job)).state == "cancelled" and w.model.asked == []
    run(go())


def test_an_agent_past_its_deadline_is_stopped_and_ends_timed_out(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            w.model.hang = True
            _, (job,) = await group(w, ["agent"])
            runner = BenchJobRunner(ONE_AGENT)
            await runner.tick()
            await asyncio.sleep(0.05)
            async with w.run.database.connection() as conn:
                await conn.execute("UPDATE bench_jobs SET deadline_at = now() - interval '1 minute'")
            await runner.tick()
            ended = await fresh(w, job)
            assert (ended.state, ended.reason) == ("timed_out", "deadline") and runner.holding == 0
            assert await state(w, job) == "timed_out"
    run(go())


def test_a_cancelled_session_is_closed_on_the_next_tick_and_only_once(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            _, (job,) = await group(w, ["claude_code"])
            runner = BenchJobRunner()
            await runner.tick()
            (sid,) = w.bridge.listed
            await cancel(w.owner, job.id)
            await runner.tick()
            await runner.tick()
            assert w.bridge.listed == {} and w.bridge.log.count(("close", sid, "")) == 1
            assert (await fresh(w, job)).state == "cancelled" and await state(w, job) == "cancelled"
    run(go())


def test_a_lapsed_agent_claim_is_retaken_with_its_pieces_and_attempts_rise(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            _, (job,) = await group(w, ["agent"])
            claimed = await services.get(BenchJobs).claim("agent", 600)
            assert claimed is not None
            made = await w.piece("note", "made", "m")
            assert await services.get(BenchJobs).made(job.id, 1, made)
            w.model.script = [RESULT(done=True, summary="s", pieces=[])]
            later = datetime.now(UTC) + timedelta(hours=1)
            runner = BenchJobRunner(ONE_AGENT, now=lambda: later)
            await runner.tick()
            await runner.idle()
            done = await fresh(w, job)
            assert (done.state, done.attempts, done.made) == ("done", 2, (made,))
            assert "earlier attempt" in str(w.model.asked[0][1].messages[0])
    run(go())
