"""The bench jobs runner (`decisions.md`, "She hands a bench job to workers and stays with the person"): the singleton, under
the lease, that takes each `due` job and runs it, and keeps each job's piece true. An `agent` job is an asyncio task
over `tools.bench_agent`, at most `max_running["agent"]` at once; a `claude_code` job is stepped each tick through
`tools.bench_session`, one list of the person's sessions per person. A job whose piece the person removed is cancelled;
a cancelled agent stops at its next step; the session of every ended Claude Code job is closed once its outputs are
collected; one past its deadline ends `timed_out`.
Everything lives in Postgres, so a pod or site that dies leaves jobs the next holder's sweep retakes.

Logs `bench_jobs.tick` (`swept`, `claimed`, `agents`, `code`, `duration_ms`), and per job `bench_jobs.finished`,
`bench_jobs.retaken` and `bench_jobs.closed` (ids, worker, attempt, state, counts). Never a title, brief, name or
summary."""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from ... import logs, services
from ...errands.bench_jobs import BenchJobs, Job, JobsUnavailable, Outcome
from ...errands.jobs_config import CONFIG, JobsConfig
from ...tools import bench_agent, bench_job_piece, bench_session
from ...workshop.model import Owner
from . import settle

log = logging.getLogger("ashley.channels")
NAME = "bench_jobs"


class BenchJobRunner:
    """`run` is the lease body: a tick, then `tick_s`, until cancelled (the lease lost), which cancels the agent tasks
    it holds; their jobs are retaken after `claim_s`."""

    def __init__(self, config: JobsConfig = CONFIG, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._config = config
        self._now = now
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._ending: set[int] = set()

    async def run(self) -> None:
        try:
            while True:
                await self.tick()
                await asyncio.sleep(self._config.tick_s)
        finally:
            for task in self._tasks.values():
                task.cancel()

    @property
    def holding(self) -> int:
        """How many agent tasks it holds."""
        return len(self._tasks)

    async def idle(self) -> None:
        """Wait for the agent tasks this runner holds to end."""
        await asyncio.gather(*self._tasks.values())

    async def tick(self) -> Counter[str]:
        """One tick; the counts it logged. A store that cannot be reached ends it, logged `bench_jobs.unavailable`."""
        started = time.perf_counter()
        counts: Counter[str] = Counter()
        try:
            await self._sweep(counts)
            await self._cancel_pieces()
            await self._closing()
            await self._agents(counts)
            await self._code(counts)
        except JobsUnavailable:
            logs.warning(log, "bench_jobs.unavailable")
        logs.info(log, "bench_jobs.tick", swept=counts["swept"], claimed=counts["claimed"], agents=self.holding,
                  code=counts["code"], duration_ms=int((time.perf_counter() - started) * 1000))
        return counts

    async def _sweep(self, counts: Counter[str]) -> None:
        store = services.get(BenchJobs)
        before = await store.unfinished()
        swept = await store.sweep(self._config.claim_s, self._now())
        counts["swept"] = swept.retaken + swept.failed + swept.timed_out
        if not counts["swept"]:
            return
        for job in before:
            now = await settle.shown(job.id, job.household_id, job.person_id)
            if now is not None and job.state != "due" and now.state == "due":
                logs.info(log, "bench_jobs.retaken", job=job.id, worker=job.worker, attempt=now.attempts)

    async def _cancel_pieces(self) -> None:
        """A job whose piece the person removed is cancelled."""
        for job in await services.get(BenchJobs).unfinished():
            if await bench_job_piece.gone(Owner(job.household_id, job.person_id), job):
                if await services.get(BenchJobs).cancel(job.household_id, job.person_id, job.id):
                    logs.info(log, "bench_jobs.cancelled", job=job.id, worker=job.worker, attempt=job.attempts)

    async def _closing(self) -> None:
        for job in await services.get(BenchJobs).due_closes():
            if await bench_session.close(job):
                await services.get(BenchJobs).closed(job.id)
                logs.info(log, "bench_jobs.closed", job=job.id, attempt=job.attempts, state=job.state)

    async def _agents(self, counts: Counter[str]) -> None:
        store = services.get(BenchJobs)
        live = {j.id: j for j in await store.active("agent")}
        for job_id, task in list(self._tasks.items()):
            job = live.get(job_id)
            if task.done():
                del self._tasks[job_id]
            elif job is None:
                if job_id not in self._ending:
                    task.cancel()
                    del self._tasks[job_id]
            elif job.deadline_at is not None and self._now() > job.deadline_at:
                task.cancel()
                del self._tasks[job_id]
                await settle.ended(job, Outcome("timed_out", "deadline"))
        while len(self._tasks) < self._config.max_running["agent"]:
            job = await store.claim("agent", self._config.claim_s)
            if job is None:
                break
            counts["claimed"] += 1
            self._tasks[job.id] = asyncio.create_task(self._agent(job))
            await settle.shown(job.id, job.household_id, job.person_id)

    async def _agent(self, job: Job) -> None:
        try:
            outcome = await bench_agent.run(job, self._config)
        except Exception as e:
            logs.warning(log, "bench_jobs.agent_failed", job=job.id, attempt=job.attempts, error=type(e).__name__)
            outcome = Outcome("failed", "error")
        self._ending.add(job.id)
        try:
            await settle.ended(job, outcome)
        finally:
            self._ending.discard(job.id)

    async def _code(self, counts: Counter[str]) -> None:
        store = services.get(BenchJobs)
        for _ in range(self._config.max_running["claude_code"]):
            job = await store.claim("claude_code", self._config.claim_s)
            if job is None:
                break
            counts["claimed"] += 1
        listed: dict[int, bench_session.Listed | None] = {}
        for job in await store.active("claude_code"):
            counts["code"] += 1
            if job.person_id not in listed:
                listed[job.person_id] = await bench_session.listed_for(job)
            outcome = await bench_session.step(job, listed[job.person_id], self._now(), self._config)
            if outcome is not None:
                await settle.ended(job, outcome)
            else:
                await settle.shown(job.id, job.household_id, job.person_id)

