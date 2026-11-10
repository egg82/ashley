"""Cancelling a job: the store's verdict, then the job's piece shown as it now stands. The runner stops an agent at
its next step and closes a Claude Code job's session."""

import logging

from .. import logs, services
from ..errands.bench_jobs import BenchJobs, Job
from ..workshop.model import Owner
from . import bench_job_piece

log = logging.getLogger("ashley.tools")


async def cancel(owner: Owner, job_id: int, bench_id: int | None = None) -> Job | None:
    """The person's job after cancelling it (or as it already was when it had ended); None when it is not theirs, or not
    on `bench_id` when that is given, in which case nothing is cancelled. Raises JobsUnavailable and what
    `Workshop.apply` raises."""
    store = services.get(BenchJobs)
    found = await store.get(owner.household_id, owner.person_id, job_id)
    if found is None or (bench_id is not None and found.bench_id != bench_id):
        return None
    changed = await store.cancel(owner.household_id, owner.person_id, job_id)
    job = await store.get(owner.household_id, owner.person_id, job_id)
    if job is None:
        return None
    if changed:
        logs.info(log, "bench_jobs.cancelled", job=job.id, worker=job.worker, attempt=job.attempts)
        await bench_job_piece.show(owner, job)
    return job
