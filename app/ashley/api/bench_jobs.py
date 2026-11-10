"""A person's Cancel on a job piece of their bench (`ashley.channels.bench_job.cancel`): the job ends `cancelled`, its
piece shows it, an agent stops at its next step and a Claude Code job's session is closed. A job that has already ended
stays as it ended."""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..channels.bench_job import JobsUnavailable, cancel
from ..workshop.workshop import WorkshopUnavailable
from .benches import BENCH_ERRORS, WRITE_ERRORS, not_found, owner_of, unavailable
from .person import Person

router = APIRouter()


class JobCancelled(BaseModel):
    """The job after the cancel: `state` is `cancelled`, or what it had already ended as."""

    model_config = ConfigDict(extra="forbid")

    job: int
    state: Literal["due", "waiting", "starting", "running", "blocked", "done", "failed", "timed_out", "cancelled"]


@router.post("/api/benches/{bench_id}/jobs/{job_id}/cancel", response_model=JobCancelled,
             responses={**WRITE_ERRORS, **BENCH_ERRORS})
async def cancel_bench_job(signed_in: Person, bench_id: int, job_id: int) -> JobCancelled | JSONResponse:
    """200 `JobCancelled`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found` for a job that is not this person's or is
    not on this bench; 503 `unavailable`."""
    try:
        job = await cancel(owner_of(signed_in), job_id, bench_id)
    except (WorkshopUnavailable, JobsUnavailable):
        return unavailable()
    if job is None:
        return not_found()
    return JobCancelled(job=job.id, state=job.state)
