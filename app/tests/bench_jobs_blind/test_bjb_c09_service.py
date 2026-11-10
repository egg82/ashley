"""The `BenchJobs` service over Postgres (I1, R2) and contract 9: claiming, attempt-guarded writes, the lapse sweep and the
retake, giving up at `max_attempts`, cancelling, and the group's settling."""

import asyncio

from ashley.errands.bench_job_model import Job
from bjb_support import World, age, cfg, job_count, limit, named, new_job, outcome, row, scenario, state_of
from contract.conversations_support import scalar

FINAL = ("done", "failed", "timed_out", "cancelled")


def lapse(w: World, job: int) -> None:
    age(w.url, job, "claimed_at", cfg().claim_s * 10 + 60)


async def relaunch(w: World, job: int) -> Job:
    lapse(w, job)
    await w.jobs.sweep(cfg().claim_s, None)
    return await w.claimed()


def test_c06_start_group_records_the_whole_group_with_one_group_id(db_url: str) -> None:
    async def body(w: World) -> None:
        group, ids = await w.start(new_job(w, title="a"), new_job(w, "claude_code", title="b"), new_job(w, title="c"))
        assert len(ids) == 3 and job_count(w.url) == 3
        assert {row(w.url, i)["group_id"] for i in ids} == {group}
        assert [state_of(w.url, i) for i in ids] == ["due"] * 3
        other, _ = await w.start(new_job(w, title="d"))
        assert other != group

    scenario(db_url, body)


def test_c05_running_counts_a_persons_unfinished_jobs_of_one_worker(db_url: str) -> None:
    async def body(w: World) -> None:
        h, p = w.owner.household_id, w.owner.person_id
        assert await w.jobs.running(h, p, "agent") == 0
        a = await w.started()
        await w.started("claude_code")
        assert (await w.jobs.running(h, p, "agent"), await w.jobs.running(h, p, "claude_code")) == (1, 1)
        job = await w.claimed()
        await w.jobs.finish(job.id, job.attempts, outcome("done", summary="ok"))
        assert await w.jobs.running(h, p, "agent") == 0 and a == job.id
        assert await w.jobs.running(h, w.mate.person_id, "claude_code") == 0

    scenario(db_url, body)


def test_c09_claim_takes_a_due_job_of_that_worker_sets_its_attempt_and_deadline(db_url: str) -> None:
    async def body(w: World) -> None:
        agent, code = await w.started(), await w.started("claude_code")
        job = await w.claimed("agent")
        assert job.id == agent and job.attempts == 1
        stored = row(w.url, agent)
        assert stored["state"] == "running" and stored["claimed_at"] is not None
        assert state_of(w.url, code) == "due"
        for worker, jid in (("agent", agent),):
            seconds = float(scalar(w.url, "SELECT extract(epoch FROM deadline_at - now()) FROM bench_jobs WHERE id = %s", (jid,)))
            assert abs(seconds - limit("deadline_min", worker) * 60) < 120

    scenario(db_url, body)


def test_c09_a_claude_code_job_is_starting_when_claimed_and_its_deadline_is_its_own(db_url: str) -> None:
    async def body(w: World) -> None:
        code = await w.started("claude_code")
        job = await w.claimed("claude_code")
        assert job.id == code and state_of(w.url, code) == "starting"
        seconds = float(scalar(w.url, "SELECT extract(epoch FROM deadline_at - now()) FROM bench_jobs WHERE id = %s", (code,)))
        assert abs(seconds - limit("deadline_min", "claude_code") * 60) < 120

    scenario(db_url, body)


def test_c09_claim_with_nothing_due_is_none_and_never_takes_a_job_twice(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await w.jobs.claim("agent", cfg().claim_s) is None
        await w.started()
        got = await asyncio.gather(w.jobs.claim("agent", cfg().claim_s), w.jobs.claim("agent", cfg().claim_s))
        assert sorted(g is None for g in got) == [False, True]

    scenario(db_url, body)


def test_c09_claim_takes_the_oldest_first(db_url: str) -> None:
    async def body(w: World) -> None:
        first, second = await w.started(title="first"), await w.started(title="second")
        age(w.url, second, "created_at", 5000)
        assert (await w.claimed()).id == second
        assert (await w.claimed()).id == first

    scenario(db_url, body)


def test_c09_heartbeat_refreshes_the_claim_only_at_the_current_attempt(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started()
        job = await w.claimed()
        lapse(w, job.id)
        assert await w.jobs.heartbeat(job.id, job.attempts) is True
        assert float(scalar(w.url, "SELECT extract(epoch FROM now() - claimed_at) FROM bench_jobs WHERE id = %s", (job.id,))) < 30
        assert await w.jobs.heartbeat(job.id, job.attempts + 1) is False
        await w.jobs.finish(job.id, job.attempts, outcome("done", summary="ok"))
        assert await w.jobs.heartbeat(job.id, job.attempts) is False

    scenario(db_url, body)


def test_c09_made_started_prompted_and_state_are_written_only_at_the_current_attempt(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started("claude_code")
        job = await w.claimed("claude_code")
        stale = job.attempts + 5
        await w.jobs.made(job.id, stale, 41)
        await w.jobs.started(job.id, stale, "sess-stale")
        await w.jobs.prompted(job.id, stale)
        await w.jobs.state(job.id, stale, "blocked")
        stored = row(w.url, job.id)
        assert stored["made"] in ([], None) and stored["session_id"] is None and stored["prompted_at"] is None
        assert stored["state"] == "starting"
        await w.jobs.made(job.id, job.attempts, 41)
        await w.jobs.started(job.id, job.attempts, "sess-1")
        await w.jobs.prompted(job.id, job.attempts)
        stored = row(w.url, job.id)
        assert stored["made"] == [41] and stored["session_id"] == "sess-1" and stored["prompted_at"] is not None

    scenario(db_url, body)


def test_c09_a_job_blocks_and_works_again(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started("claude_code")
        job = await w.claimed("claude_code")
        await w.jobs.started(job.id, job.attempts, "sess-1")
        await w.jobs.state(job.id, job.attempts, "running")
        assert state_of(w.url, job.id) == "running"
        await w.jobs.state(job.id, job.attempts, "blocked")
        assert state_of(w.url, job.id) == "blocked"
        await w.jobs.state(job.id, job.attempts, "running")
        assert state_of(w.url, job.id) == "running"

    scenario(db_url, body)


def test_c09_finish_records_the_outcome_once_and_only_at_the_current_attempt(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started()
        job = await w.claimed()
        assert await w.jobs.finish(job.id, job.attempts + 3, outcome("done", summary="stale")) is False
        assert state_of(w.url, job.id) == "running"
        assert await w.jobs.finish(job.id, job.attempts, outcome("done", summary="the summary", outputs=(4, 5), refused=2))
        stored = row(w.url, job.id)
        assert (stored["state"], stored["summary"], stored["outputs"], stored["refused"]) == ("done", "the summary", [4, 5], 2)
        assert stored["finished_at"] is not None
        assert await w.jobs.finish(job.id, job.attempts, outcome("failed", reason="late")) is False
        assert row(w.url, job.id)["state"] == "done"

    scenario(db_url, body)


def test_c09_a_failed_job_keeps_its_reason_code(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started()
        job = await w.claimed()
        await w.jobs.finish(job.id, job.attempts, outcome("failed", reason="bridge_unavailable"))
        stored = row(w.url, job.id)
        assert (stored["state"], stored["reason"]) == ("failed", "bridge_unavailable")

    scenario(db_url, body)


def test_c09_sweep_puts_a_lapsed_running_agent_job_back_to_due_and_keeps_its_pieces(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started()
        job = await w.claimed()
        await w.jobs.made(job.id, job.attempts, 41)
        lapse(w, job.id)
        await w.jobs.sweep(cfg().claim_s, None)
        stored = row(w.url, job.id)
        assert stored["state"] == "due" and stored["made"] == [41]
        again = await w.claimed()
        assert again.id == job.id and again.attempts == job.attempts + 1
        assert list(again.made) == [41]

    scenario(db_url, body)


def test_c09_sweep_leaves_a_live_claim_alone(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started()
        job = await w.claimed()
        await w.jobs.sweep(cfg().claim_s, None)
        assert state_of(w.url, job.id) == "running"

    scenario(db_url, body)


def test_c09_the_old_attempts_writes_change_nothing_after_a_retake(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started()
        first = await w.claimed()
        again = await relaunch(w, first.id)
        assert again.attempts == first.attempts + 1
        await w.jobs.made(first.id, first.attempts, 77)
        assert await w.jobs.heartbeat(first.id, first.attempts) is False
        assert await w.jobs.finish(first.id, first.attempts, outcome("done", summary="zombie")) is False
        stored = row(w.url, first.id)
        assert stored["state"] == "running" and stored["made"] in ([], None) and stored["summary"] is None

    scenario(db_url, body)


def test_c09_at_max_attempts_the_job_ends_failed_with_reason_attempts(db_url: str) -> None:
    async def body(w: World) -> None:
        job_id = await w.started()
        claims = 0
        for _ in range(limit("max_attempts") + 2):
            job = await w.jobs.claim("agent", cfg().claim_s)
            if job is None:
                break
            claims += 1
            lapse(w, job.id)
            await w.jobs.sweep(cfg().claim_s, None)
        stored = row(w.url, job_id)
        assert (stored["state"], stored["reason"]) == ("failed", "attempts")
        assert stored["finished_at"] is not None and claims <= limit("max_attempts") + 1

    scenario(db_url, body)


def test_c09_one_below_max_attempts_is_still_retaken(db_url: str) -> None:
    async def body(w: World) -> None:
        job_id = await w.started()
        for _ in range(limit("max_attempts") - 1):
            job = await w.claimed()
            lapse(w, job.id)
            await w.jobs.sweep(cfg().claim_s, None)
        assert state_of(w.url, job_id) == "due"

    scenario(db_url, body)


def test_c15_cancel_ends_a_job_of_the_person_once(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await w.started()
        h, p = w.owner.household_id, w.owner.person_id
        assert await w.jobs.cancel(h, w.mate.person_id, job) is False
        assert state_of(w.url, job) == "due"
        assert await w.jobs.cancel(h, p, job) is True
        assert state_of(w.url, job) == "cancelled"
        assert await w.jobs.cancel(h, p, job) is False
        assert await w.jobs.cancel(h, p, 999999) is False

    scenario(db_url, body)


def test_c15_a_finished_job_cannot_be_cancelled_and_a_cancelled_one_cannot_finish(db_url: str) -> None:
    async def body(w: World) -> None:
        h, p = w.owner.household_id, w.owner.person_id
        done = await w.started()
        job = await w.claimed()
        await w.jobs.finish(job.id, job.attempts, outcome("done", summary="ok"))
        assert await w.jobs.cancel(h, p, done) is False and state_of(w.url, done) == "done"
        running = await w.started(title="b")
        job = await w.claimed()
        assert await w.jobs.cancel(h, p, running) is True
        assert await w.jobs.heartbeat(job.id, job.attempts) is False
        assert await w.jobs.finish(job.id, job.attempts, outcome("done", summary="late")) is False
        assert state_of(w.url, running) == "cancelled"

    scenario(db_url, body)


def test_c15_a_cancelled_claude_code_job_with_a_session_is_due_for_its_session_to_close(db_url: str) -> None:
    async def body(w: World) -> None:
        h, p = w.owner.household_id, w.owner.person_id
        live = await w.started("claude_code")
        job = await w.claimed("claude_code")
        await w.jobs.started(job.id, job.attempts, "sess-9")
        idle = await w.started(title="idle")
        assert [j.id for j in await w.jobs.due_closes()] == []
        await w.jobs.cancel(h, p, live)
        await w.jobs.cancel(h, p, idle)
        assert [j.id for j in await w.jobs.due_closes()] == [live]

    scenario(db_url, body)


def test_c20_the_group_is_settled_only_when_every_job_is_final(db_url: str) -> None:
    async def body(w: World) -> None:
        group, (a, b, c) = await w.start(new_job(w, title="a"), new_job(w, "claude_code", title="b"), new_job(w, title="c"))
        assert await w.jobs.group_settled(group) is None
        first = await w.claimed("agent")
        await w.jobs.finish(first.id, first.attempts, outcome("done", summary="a"))
        assert await w.jobs.group_settled(group) is None
        second = await w.claimed("agent")
        await w.jobs.finish(second.id, second.attempts, outcome("failed", reason="x"))
        assert await w.jobs.group_settled(group) is None
        code = await w.claimed("claude_code")
        await w.jobs.state(code.id, code.attempts, "blocked")
        assert await w.jobs.group_settled(group) is None, "blocked is not final"
        await w.jobs.finish(code.id, code.attempts, outcome("timed_out", reason="deadline"))
        settled = await w.jobs.group_settled(group)
        assert settled is not None and sorted(j.id for j in settled) == sorted((a, b, c))

    scenario(db_url, body)


def test_c20_a_cancelled_job_counts_as_final_for_the_group(db_url: str) -> None:
    async def body(w: World) -> None:
        group, (a, b) = await w.start(new_job(w, title="a"), new_job(w, title="b"))
        await w.jobs.cancel(w.owner.household_id, w.owner.person_id, a)
        job = await w.claimed()
        assert job.id == b
        await w.jobs.finish(job.id, job.attempts, outcome("done", summary="ok"))
        assert await w.jobs.group_settled(group) is not None

    scenario(db_url, body)


def test_c20_an_unknown_group_is_not_settled(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await w.jobs.group_settled(424242) is None

    scenario(db_url, body)


def test_c06_get_answers_only_the_owner_of_the_job(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await w.started(pieces=[named(5, True)])
        got = await w.jobs.get(w.owner.household_id, w.owner.person_id, job)
        assert got is not None and got.id == job and got.state == "due"
        assert await w.jobs.get(w.owner.household_id, w.mate.person_id, job) is None
        assert await w.jobs.get(w.owner.household_id + 1, w.owner.person_id, job) is None
        assert await w.jobs.get(w.owner.household_id, w.owner.person_id, job + 1000) is None

    scenario(db_url, body)
