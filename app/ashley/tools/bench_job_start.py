"""Starting a group of jobs from a bench: every job checked first, so a call that fails records nothing; then each job's
piece added, the group stored in one transaction, the pieces told their job, and one `bench_job` watch armed for the
group. Returns before any worker runs."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .. import logs, services
from ..errands.bench_jobs import BenchJobs, Job, JobsUnavailable, NewJob, Worker
from ..errands.jobs_config import CONFIG, JobsConfig
from ..watches.bench_job import NAME as WATCH, items_of
from ..watches.config import CONFIG as WATCHES
from ..watches.model import Arm
from ..watches.watches import Watches, WatchesUnavailable
from ..workshop.commands import Remove
from ..workshop.model import RUNNER, Owner
from ..workshop.workshop import Workshop
from . import bench_job_piece, tainted
from .bench_job_args import Draft
from .bench_job_parts import NoSuchPiece, parts

log = logging.getLogger("ashley.tools")
GROUP_LABEL = "handed off"


class Refused(Exception):
    """A hand-off that recorded nothing: `reason` is the result's."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Started:
    group: int
    jobs: tuple[Job, ...]
    watched: bool


async def check(owner: Owner, bench_id: int, drafts: tuple[Draft, ...], config: JobsConfig = CONFIG) -> None:
    """Raises Refused `no_such_piece`, `too_large` or `too_many` for the first job that is not startable."""
    for d in drafts:
        try:
            got = await parts(owner, bench_id, d.pieces, config)
        except NoSuchPiece as e:
            raise Refused("no_such_piece") from e
        if len(d.pieces) > config.max_pieces_in or sum(p.size for p in got) > config.max_bytes_in:
            raise Refused("too_large")
    workers: set[Worker] = {d.worker for d in drafts}
    for worker in workers:
        asked = sum(d.worker == worker for d in drafts)
        if await services.get(BenchJobs).running(owner.household_id, owner.person_id, worker) + asked > config.max_running[worker]:
            raise Refused("too_many")


async def start(owner: Owner, bench_id: int, said: tuple[int, int], drafts: tuple[Draft, ...],
                waiting: bool = False) -> Started:
    """Record the group and arm its watch; a Claude Code job is recorded `waiting` when `waiting` (the person's machine
    did not answer). Raises Refused `unavailable`; what `check` raises is the caller's to call first."""
    pieces: list[int] = []
    try:
        for d in drafts:
            applied = await bench_job_piece.add(owner, bench_id, d.worker, d.title)
            if applied.piece_id is None:
                raise Refused("unavailable")
            pieces.append(applied.piece_id)
        group, ids = await services.get(BenchJobs).start_group(tuple(
            NewJob(owner.household_id, owner.person_id, bench_id, said[0], said[1], d.worker, d.title, d.brief,
                   d.pieces, piece, waiting and d.worker == "claude_code") for d, piece in zip(drafts, pieces, strict=True)))
        jobs = await _shown(owner, ids)
    except Exception as e:
        await _undo(owner, bench_id, pieces)
        if isinstance(e, Refused):
            raise
        logs.warning(log, "bench_jobs.unstarted", person=owner.person_id, jobs=len(drafts), error=type(e).__name__)
        raise Refused("unavailable") from e
    watched = await _arm(owner, bench_id, group, jobs, said)
    for j in jobs:
        logs.info(log, "bench_jobs.started", job=j.id, group=group, worker=j.worker, attempt=j.attempts, pieces=len(j.pieces),
                  state=j.state, watched=watched)
    return Started(group, jobs, watched)


async def _shown(owner: Owner, ids: tuple[int, ...]) -> tuple[Job, ...]:
    out: list[Job] = []
    for i in ids:
        job = await services.get(BenchJobs).get(owner.household_id, owner.person_id, i)
        if job is None:
            raise JobsUnavailable("a job just stored is not there")
        await bench_job_piece.show(owner, job)
        out.append(job)
    return tuple(out)


async def _undo(owner: Owner, bench_id: int, pieces: list[int]) -> None:
    """Take the pieces a failed start added off the bench again."""
    for piece in pieces:
        try:
            await services.get(Workshop).apply(owner, bench_id, Remove(RUNNER, piece))
        except Exception:
            logs.warning(log, "bench_jobs.unstarted_piece_kept", piece=piece)


async def _arm(owner: Owner, bench_id: int, group: int, jobs: tuple[Job, ...], said: tuple[int, int]) -> bool:
    """Watch the group from the state it is in; False when that could not be recorded, which she tells the person."""
    kind = WATCHES.kinds[WATCH]
    expires = datetime.now(UTC) + timedelta(hours=kind.handoff_hours)
    taint = tainted.current()
    arm = Arm(owner.household_id, owner.person_id, WATCH, str(group), GROUP_LABEL, bench_id, "handoff", kind.track,
              kind.when, kind.handoff_until, None, kind.interval_s, expires, items_of(str(group), jobs),
              taint=taint, made_in=said if taint is not None else None)
    try:
        await services.get(Watches).arm(arm)
    except (WatchesUnavailable, ValueError):
        logs.warning(log, "bench_jobs.unwatched", group=group)
        return False
    return True


