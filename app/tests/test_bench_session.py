"""The Claude Code worker of a bench job (`ashley.tools.bench_session`) over a real database and an in-memory bridge:
it starts a session under a root, uploads only the pieces the job names under names made from their ids, prompts with the
brief and the code footer, goes `running`, turns `blocked` when the session does, and on `done` takes `out/` into file
pieces with `RESULT.md` as the summary; a retake reuses the session and prompts only when it has not moved."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ashley import services
from ashley.errands.bench_jobs import BenchJobs, Job, Named
from ashley.tools import bench_session
from ashley.workshop.workshop import Workshop
from bench_jobs_support import Jobs, db_url as db_url, jobs_world, migrated_template as migrated_template
from contract.conversations_support import run

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 24


async def coded(w: Jobs, pieces: tuple[Named, ...] = ()) -> Job:
    store = services.get(BenchJobs)
    await store.start(w.s.new("claude_code", pieces=pieces))
    job = await store.claim("claude_code", 600)
    assert job is not None
    return job


async def fresh(w: Jobs, job: Job) -> Job:
    seen = await services.get(BenchJobs).get(w.s.household, w.s.person, job.id)
    assert seen is not None
    return seen


def test_a_job_starts_under_a_root_uploads_only_what_it_names_and_is_prompted(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            named = await w.piece("code", "T", "print(1)")
            await w.piece("note", "Other", "secret-body")
            job = await coded(w, (Named(named),))
            assert await bench_session.step(job) is None
            (sid,) = w.bridge.listed
            assert w.bridge.listed[sid].dir == f"/work/ashley-jobs/j{job.id}"
            assert w.bridge.uploads[sid] == {f"p{named}.py": b"print(1)"}
            (sent,) = w.bridge.prompts
            assert sent.startswith("brief") and bench_session.footer() in sent and "secret-body" not in sent
            now = await fresh(w, job)
            assert (now.state, now.session_id) == ("running", sid) and now.prompted_at is not None
    run(go())


def test_it_goes_blocked_and_back_and_collects_out_when_the_session_is_done(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            assert await bench_session.step(job) is None
            (sid,) = w.bridge.listed
            running = await fresh(w, job)
            w.bridge.state(sid, "blocked", 6)
            assert await bench_session.step(running) is None and (await fresh(w, job)).state == "blocked"
            w.bridge.state(sid, "working", 7)
            assert await bench_session.step(await fresh(w, job)) is None and (await fresh(w, job)).state == "running"
            w.bridge.state(sid, "idle", 5)
            assert await bench_session.step(await fresh(w, job)) is None
            w.bridge.files[sid] = {"RESULT.md": b"It built the thing.", "out.png": PNG, "notes.txt": b"hi",
                                   "bad.exe": b"MZ\x00"}
            w.bridge.state(sid, "done", 8)
            out = await bench_session.step(await fresh(w, job))
            assert out is not None and (out.state, out.summary, out.refused) == ("done", "It built the thing.", 1)
            assert len(out.outputs) == 2
            view = await services.get(Workshop).read(w.owner, w.s.bench)
            assert sorted(p.kind for p in view.pieces if p.id in out.outputs) == ["file", "image"]
            assert not [c for c in w.bridge.log if c[0] == "close"]
    run(go())


def test_idle_after_working_ends_it_and_a_past_deadline_collects_as_it_stands(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            await bench_session.step(job)
            (sid,) = w.bridge.listed
            w.bridge.files[sid] = {"a.txt": b"x"}
            w.bridge.state(sid, "idle", 9)
            out = await bench_session.step(await fresh(w, job))
            assert out is not None and (out.state, len(out.outputs)) == ("done", 1)
            other = await coded(w)
            await bench_session.step(other)
            late = (await fresh(w, other)).deadline_at
            assert late is not None
            sid2 = (await fresh(w, other)).session_id
            assert sid2 is not None
            w.bridge.files[sid2] = {"RESULT.md": b"partial", "b.txt": b"y"}
            w.bridge.state(sid2, "working", 10)
            out = await bench_session.step(await fresh(w, other), now=late + timedelta(minutes=1))
            assert out is not None and (out.state, out.reason, out.summary) == ("timed_out", "deadline", "partial")
    run(go())


async def retaken(w: Jobs, job: Job) -> Job:
    """The job after its claim lapsed and it was claimed again."""
    store = services.get(BenchJobs)
    await store.sweep(600, datetime.now(UTC) + timedelta(hours=1))
    again = await store.claim("claude_code", 600)
    assert again is not None and again.id == job.id and again.attempts == job.attempts + 1
    return again


def test_a_retake_reuses_its_session_and_prompts_only_when_the_session_has_not_moved(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            w.bridge.refuse_prompt = "busy"
            assert await bench_session.step(job) is None
            (sid,) = w.bridge.listed
            assert (await fresh(w, job)).state == "starting" and w.bridge.prompts == []
            w.bridge.refuse_prompt = None
            second = await retaken(w, job)
            assert second.session_id == sid
            assert await bench_session.step(second) is None
            assert len(w.bridge.prompts) == 1 and list(w.bridge.listed) == [sid]
    run(go())


def test_a_retake_does_not_prompt_a_session_that_already_moved(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            w.bridge.refuse_prompt = "busy"
            assert await bench_session.step(job) is None
            (sid,) = w.bridge.listed
            sent = len(w.bridge.prompts)
            w.bridge.refuse_prompt = None
            w.bridge.state(sid, "working", 99)
            third = await retaken(w, await fresh(w, job))
            assert await bench_session.step(third) is None
            assert len(w.bridge.prompts) == sent and (await fresh(w, job)).state == "running"
    run(go())


def test_no_roots_fails_the_job_and_a_down_bridge_makes_it_wait(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            w.bridge.down = True
            assert await bench_session.step(job) is None and (await fresh(w, job)).state == "waiting"
            other = await coded(w)
            w.bridge.down, w.bridge.roots = False, None
            out = await bench_session.step(other)
            assert out is not None and (out.state, out.reason) == ("failed", "no_roots")
    run(go())


async def waiting(w: Jobs) -> Job:
    """A claimed job whose bridge went down as it started, so it is `waiting`."""
    job = await coded(w)
    w.bridge.down = True
    assert await bench_session.step(job) is None
    return await fresh(w, job)


def test_a_waiting_job_stays_while_the_bridge_is_silent_and_is_started_again_once_it_answers(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await waiting(w)
            assert job.state == "waiting" and w.bridge.log == []
            assert await bench_session.step(job) is None and (await fresh(w, job)).state == "waiting"
            w.bridge.down = False
            assert await bench_session.step(job) is None
            assert (await fresh(w, job)).state == "due" and w.bridge.log == []
            again = await services.get(BenchJobs).claim("claude_code", 600)
            assert again is not None and again.id == job.id and again.attempts == job.attempts + 1
            assert await bench_session.step(again) is None
            assert (await fresh(w, job)).state == "running" and len(w.bridge.prompts) == 1
    run(go())


def test_a_waiting_job_past_its_deadline_fails_with_the_machine_as_the_reason(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await waiting(w)
            assert job.deadline_at is not None
            out = await bench_session.step(job, now=job.deadline_at + timedelta(minutes=1))
            assert out is not None and (out.state, out.reason) == ("failed", "herdr_unavailable")
            w.bridge.down = False
            before = await bench_session.step(job, now=job.deadline_at - timedelta(minutes=1))
            assert before is None
    run(go())


def test_a_bridge_that_refuses_fails_a_starting_or_waiting_job_at_once(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            starting = await coded(w)
            gone = await waiting(w)
            w.bridge.down = False
            w.bridge.refuse = "bad_token"
            for job in (starting, gone):
                out = await bench_session.step(job)
                assert out is not None and (out.state, out.reason) == ("failed", "bridge_refused")
    run(go())


def test_closing_a_cancelled_job_closes_its_session(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            await bench_session.step(job)
            (sid,) = w.bridge.listed
            await services.get(BenchJobs).cancel(w.s.household, w.s.person, job.id)
            (cancelled,) = await services.get(BenchJobs).due_closes()
            assert await bench_session.close(cancelled) and w.bridge.listed == {} and ("close", sid, "") in w.bridge.log
            assert await bench_session.close(replace(cancelled, session_id=None))
    run(go())


def test_closing_asks_again_when_the_bridge_is_silent_and_gives_up_when_it_refuses(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            await bench_session.step(job)
            ended = await fresh(w, job)
            w.bridge.down = True
            assert not await bench_session.close(ended)
            w.bridge.down, w.bridge.refuse = False, "bad_token"
            assert await bench_session.close(ended) and len(w.bridge.listed) == 1
            w.bridge.refuse = "not_found"
            assert await bench_session.close(ended) and len(w.bridge.listed) == 1
            w.bridge.refuse = None
            assert await bench_session.close(ended) and w.bridge.listed == {}
    run(go())


def test_a_job_started_after_its_cancel_closes_the_session_it_made(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await coded(w)
            await services.get(BenchJobs).cancel(w.s.household, w.s.person, job.id)
            out = await bench_session.step(job)
            assert out is not None and out.state == "cancelled" and w.bridge.listed == {}
    run(go())

