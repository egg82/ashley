"""How a bench job ends or changes, as the runner records it: the store's verdict, the job's piece shown as it now
stands, and the log line. A write that finds the job no longer at its attempt (cancelled, swept) records nothing, and
so logs nothing: the verdict that got there first is the job's."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from ... import logs, services
from ...errands.bench_jobs import BenchJobs, Job, Outcome
from ...tools import bench_job_piece
from ...workshop.model import Owner

log = logging.getLogger("ashley.channels")


async def shown(job_id: int, household_id: int, person_id: int) -> Job | None:
    """The job as stored now, its piece rewritten to show it. A piece that cannot be written is left; the next tick
    shows it. Raises JobsUnavailable."""
    job = await services.get(BenchJobs).get(household_id, person_id, job_id)
    if job is not None:
        try:
            await bench_job_piece.show(Owner(household_id, person_id), job)
        except Exception as e:
            logs.warning(log, "bench_jobs.piece_unshown", job=job.id, error=type(e).__name__)
    return job


async def ended(job: Job, outcome: Outcome, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> bool:
    """Record `outcome` of `job` at its attempt; whether it took. Raises JobsUnavailable."""
    took = await services.get(BenchJobs).finish(job.id, job.attempts, outcome)
    if not took:
        return False
    logs.info(log, "bench_jobs.finished", job=job.id, group=job.group_id, worker=job.worker, attempt=job.attempts,
              state=outcome.state, reason=outcome.reason, outputs=len(outcome.outputs), refused=outcome.refused,
              duration_ms=int((clock() - job.created_at).total_seconds() * 1000))
    await shown(job.id, job.household_id, job.person_id)
    return True
