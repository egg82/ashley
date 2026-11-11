"""The bench_jobs table through `PostgresBenchJobs`: a group stored whole, a claim that takes the oldest due job of a
worker once, writes that need the attempt they were claimed at, cancel by its owner alone, the sweep's verdicts, and a
group that settles only when every job in it is final."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ashley.errands.bench_jobs import Named, NullBenchJobs, JobsUnavailable, Outcome
from bench_jobs_support import db_url as db_url, migrated_template as migrated_template, setting, store
from contract.conversations_support import run, scalar
import pytest


def test_a_group_is_stored_whole_and_settles_when_every_job_is_final(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            group, ids = await jobs.start_group((s.new(piece=1, pieces=(Named(4, True), Named(5))), s.new("claude_code", 2)))
            assert len(ids) == 2 and ids[0] != ids[1]
            assert await jobs.running(s.household, s.person, "agent") == 1
            assert await jobs.running(s.household, s.person, "claude_code") == 1
            first = await jobs.get(s.household, s.person, ids[0])
            assert first is not None and first.group_id == group and first.state == "due"
            assert first.pieces == (Named(4, True), Named(5, False)) and first.attempts == 0
            assert [j.id for j in await jobs.group(s.household, s.person, group)] == list(ids)
            assert await jobs.group_settled(group) is None
            a = await jobs.claim("agent", 600)
            assert a is not None and a.id == ids[0] and a.state == "running" and a.attempts == 1
            assert a.deadline_at is not None
            assert await jobs.finish(a.id, 1, Outcome("done", None, "ok", (7,), 1))
            assert await jobs.group_settled(group) is None
            assert await jobs.cancel(s.household, s.person, ids[1])
            settled = await jobs.group_settled(group)
            assert settled is not None and [j.state for j in settled] == ["done", "cancelled"]
            assert (settled[0].summary, settled[0].outputs, settled[0].refused) == ("ok", (7,), 1)
            assert await jobs.running(s.household, s.person, "agent") == 0
    run(go())


def test_a_claim_takes_the_oldest_due_job_of_its_worker_once(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, ids = await jobs.start_group((s.new("claude_code"), s.new("agent"), s.new("agent")))
            code = await jobs.claim("claude_code", 600)
            assert code is not None and (code.id, code.state) == (ids[0], "starting")
            assert await jobs.claim("claude_code", 600) is None
            first = await jobs.claim("agent", 600)
            second = await jobs.claim("agent", 600)
            assert first is not None and second is not None and (first.id, second.id) == (ids[1], ids[2])
            assert await jobs.claim("agent", 600) is None
            assert [j.id for j in await jobs.active("agent")] == [ids[1], ids[2]]
    run(go())


def test_a_write_naming_a_stale_attempt_changes_nothing(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, (job,) = await jobs.start_group((s.new(),))
            got = await jobs.claim("agent", 600)
            assert got is not None
            assert not await jobs.heartbeat(job, 2) and not await jobs.made(job, 2, 9)
            assert not await jobs.finish(job, 2, Outcome("done"))
            assert await jobs.heartbeat(job, 1) and await jobs.made(job, 1, 9) and await jobs.made(job, 1, 9)
            seen = await jobs.get(s.household, s.person, job)
            assert seen is not None and seen.made == (9,)
            assert await jobs.finish(job, 1, Outcome("failed", "boom"))
            assert not await jobs.heartbeat(job, 1) and not await jobs.finish(job, 1, Outcome("done"))
            assert not await jobs.made(job, 1, 10)
    run(go())
    assert scalar(db_url, "SELECT state || reason FROM bench_jobs") == "failedboom"


def test_only_the_owner_cancels_and_a_cancelled_session_is_listed_until_closed(db_url: str) -> None:
    s = setting(db_url)
    other = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, (job,) = await jobs.start_group((s.new("claude_code"),))
            got = await jobs.claim("claude_code", 600)
            assert got is not None
            assert await jobs.started(job, 1, "sess")
            assert not await jobs.cancel(other.household, other.person, job)
            assert not await jobs.cancel(s.household, other.person, job)
            assert await jobs.cancel(s.household, s.person, job) and not await jobs.cancel(s.household, s.person, job)
            assert not await jobs.prompted(job, 1) and not await jobs.state(job, 1, "running")
            assert [j.id for j in await jobs.due_closes()] == [job]
            await jobs.closed(job)
            assert await jobs.due_closes() == ()
    run(go())


def test_every_ended_claude_code_job_with_a_session_is_due_for_its_session_to_close_until_closed(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, ids = await jobs.start_group(tuple(s.new("claude_code", i + 1) for i in range(5)) + (s.new("agent", 9),))
            for _ in range(5):
                got = await jobs.claim("claude_code", 600)
                assert got is not None
                assert await jobs.started(got.id, 1, f"sess-{got.id}")
            a, b, c, d, e, agent = ids
            assert await jobs.finish(a, 1, Outcome("done"))
            assert await jobs.finish(b, 1, Outcome("failed", "x"))
            assert await jobs.finish(c, 1, Outcome("timed_out", "deadline"))
            assert await jobs.cancel(s.household, s.person, d)
            got = await jobs.claim("agent", 600)
            assert got is not None and await jobs.finish(agent, 1, Outcome("done"))
            assert [j.id for j in await jobs.due_closes()] == [a, b, c, d]
            await jobs.closed(a)
            assert [j.id for j in await jobs.due_closes()] == [b, c, d]
            assert e not in [j.id for j in await jobs.due_closes()]
    run(go())


def test_a_claude_code_job_moves_through_starting_running_and_blocked(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, (job,) = await jobs.start_group((s.new("claude_code"),))
            assert await jobs.claim("claude_code", 600) is not None
            assert not await jobs.prompted(job, 1)
            assert await jobs.started(job, 1, "sess") and await jobs.prompted(job, 1)
            assert await jobs.state(job, 1, "blocked") and not await jobs.state(job, 1, "blocked")
            assert await jobs.state(job, 1, "running") and await jobs.state(job, 1, "blocked")
            assert await jobs.state(job, 1, "running")
            seen = await jobs.get(s.household, s.person, job)
            assert seen is not None and (seen.state, seen.session_id) == ("running", "sess")
            assert seen.prompted_at is not None
    run(go())


def test_the_sweep_retakes_a_lapsed_claim_then_fails_it_at_max_attempts(db_url: str) -> None:
    s = setting(db_url)
    later = datetime.now(UTC) + timedelta(hours=1)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, (job,) = await jobs.start_group((s.new(),))
            for attempt in (1, 2):
                assert await jobs.claim("agent", 600) is not None
                assert (await jobs.sweep(600, datetime.now(UTC))).retaken == 0
                counts = await jobs.sweep(600, later)
                assert (counts.retaken, counts.failed) == (1, 0)
                again = await jobs.get(s.household, s.person, job)
                assert again is not None and (again.state, again.attempts) == ("due", attempt)
            got = await jobs.claim("agent", 600)
            assert got is not None and got.attempts == 3
            assert (await jobs.sweep(600, later)).failed == 1
            ended = await jobs.get(s.household, s.person, job)
            assert ended is not None and (ended.state, ended.reason) == ("failed", "attempts")
    run(go())


def test_the_sweep_leaves_a_running_claude_code_job_and_ends_a_late_group(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            group, (code, agent) = await jobs.start_group((s.new("claude_code"), s.new("agent")))
            assert await jobs.claim("claude_code", 600) is not None
            assert await jobs.started(code, 1, "sess") and await jobs.state(code, 1, "running")
            quiet = await jobs.sweep(600, datetime.now(UTC) + timedelta(minutes=100))
            assert (quiet.retaken, quiet.failed, quiet.timed_out) == (0, 0, 0)
            assert [j.state for j in await jobs.group(s.household, s.person, group)] == ["running", "due"]
            counts = await jobs.sweep(600, datetime.now(UTC) + timedelta(minutes=201))
            assert counts.timed_out == 2
            settled = await jobs.group_settled(group)
            assert settled is not None and {j.state for j in settled} == {"timed_out"}
            assert {j.reason for j in settled} == {"group_timeout"}
            assert await jobs.get(s.household, s.person, agent) is not None
    run(go())


def test_idle_is_recorded_once_until_the_session_works_again_and_a_nudge_is_recorded_once(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            (code,) = (await jobs.start_group((s.new("claude_code"),)))[1]
            assert await jobs.claim("claude_code", 600) is not None
            first = datetime.now(UTC)
            assert await jobs.idle(code, 1, first) == first
            assert await jobs.idle(code, 1, first + timedelta(seconds=30)) == first
            assert await jobs.busy(code, 1)
            later = first + timedelta(seconds=90)
            assert await jobs.idle(code, 1, later) == later
            assert await jobs.nudged(code, 1) and not await jobs.nudged(code, 1) and not await jobs.nudged(code, 0)
            row = await jobs.get(s.household, s.person, code)
            assert row is not None and row.idle_since == later and row.nudged_at is not None
            assert await jobs.busy(code, 1)
            assert not await jobs.nudged(code, 1)
            row = await jobs.get(s.household, s.person, code)
            assert row is not None and row.idle_since is None and row.nudged_at is not None
    run(go())


def test_the_null_store_raises_and_an_unknown_group_is_not_settled(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as jobs:
            assert await jobs.group_settled(123456) is None
        with pytest.raises(JobsUnavailable):
            await NullBenchJobs().running(1, 1, "agent")
    run(go())


def test_a_waiting_job_is_live_with_a_deadline_from_hand_off_and_only_a_resume_makes_it_due(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, (job,) = await jobs.start_group((replace(s.new("claude_code"), waiting=True),))
            waiting = await jobs.get(s.household, s.person, job)
            assert waiting is not None and (waiting.state, waiting.attempts) == ("waiting", 0)
            assert waiting.deadline_at is not None and waiting.deadline_at > waiting.created_at
            assert await jobs.claim("claude_code", 600) is None
            assert [j.id for j in await jobs.active("claude_code")] == [job]
            assert not await jobs.state(job, 0, "waiting") and not await jobs.state(job, 0, "running")
            assert not await jobs.resume(job, 1) and await jobs.resume(job, 0) and not await jobs.resume(job, 0)
            again = await jobs.claim("claude_code", 600)
            assert again is not None and (again.state, again.attempts) == ("starting", 1)
            assert again.deadline_at == waiting.deadline_at
            assert await jobs.state(job, 1, "waiting") and not await jobs.state(job, 1, "waiting")
            assert await jobs.finish(job, 1, Outcome("failed", "herdr_unavailable"))
            assert not await jobs.resume(job, 1)
    run(go())


def test_the_sweep_leaves_a_waiting_job_alone_until_its_group_times_out(db_url: str) -> None:
    s = setting(db_url)

    async def go() -> None:
        async with store(db_url) as jobs:
            _, (job,) = await jobs.start_group((replace(s.new("claude_code"), waiting=True),))
            far = datetime.now(UTC) + timedelta(minutes=190)
            counts = await jobs.sweep(600, far)
            assert (counts.retaken, counts.failed, counts.timed_out) == (0, 0, 0)
            assert (await jobs.get(s.household, s.person, job)) is not None
            counts = await jobs.sweep(600, datetime.now(UTC) + timedelta(minutes=300))
            ended = await jobs.get(s.household, s.person, job)
            assert counts.timed_out == 1 and ended is not None and ended.state == "timed_out"
    run(go())
