"""A bench job's `job` piece (`workshop.job_body`): added and rewritten by the jobs' runner alone (`model.RUNNER`), so
the person sees the job's state on the bench and every change is a logged, undoable-by-nobody Command on Live."""

from datetime import datetime

from ..errands.bench_jobs import BenchJobs, Job
from .. import services
from ..workshop import job_body, rules as workshop_rules
from ..workshop.commands import Add, Edit
from ..workshop.model import RUNNER, Owner, Text
from ..workshop.workshop import Applied, Workshop

RULES = workshop_rules.load()
KIND = "job"


def body_of(job: Job) -> str:
    """The body that shows `job` as it stands."""
    def at(t: datetime | None) -> str | None:
        return None if t is None else t.isoformat()

    return job_body.body_of(job_body.JobBody(job.id, job.worker, job.title, job.state, at(job.created_at),
                                             at(job.deadline_at), at(job.finished_at), job.outputs, job.refused,
                                             job.reason))


async def add(owner: Owner, bench_id: int, worker: str, title: str) -> Applied:
    """A `due` job piece last on the bench, not yet naming its job. Raises what `Workshop.apply` raises."""
    body = job_body.body_of(job_body.JobBody(None, worker, title, "due", None, None, None, (), 0, None))
    return await services.get(Workshop).apply(owner, bench_id, Add(RUNNER, KIND, Text(title[:RULES.title_max_chars], body),
                                                                   "small"))


async def show(owner: Owner, job: Job) -> bool:
    """Rewrite the job's piece to show the job as it stands now (`job` says which); False when the piece is no longer on
    the bench's layout. Raises what `Workshop.apply` and `BenchJobs.get` raise."""
    for _ in range(2):
        job = await services.get(BenchJobs).get(job.household_id, job.person_id, job.id) or job
        view = await services.get(Workshop).read(owner, job.bench_id)
        piece = next((p for p in view.pieces if p.id == job.piece_id), None)
        if piece is None:
            return False
        body = body_of(job)
        if piece.text.body == body:
            return True
        applied = await services.get(Workshop).apply(owner, job.bench_id,
                                                     Edit(RUNNER, piece.id, piece.version, Text(piece.text.title, body)))
        if applied.outcome == "accepted":
            return True
    return False


async def gone(owner: Owner, job: Job) -> bool:
    """Whether the job's piece is neither on the bench's layout nor on its shelf: the person removed it. Raises what
    `Workshop.read` raises."""
    view = await services.get(Workshop).read(owner, job.bench_id)
    return not any(p.id == job.piece_id for p in (*view.pieces, *view.shelf))
