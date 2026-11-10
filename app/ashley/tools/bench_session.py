"""A Claude Code worker for a bench job (`ashley.errands.bench_jobs`): a session on the person's herdr bridge, started
under `<first root>/ashley-jobs/j<job id>`, given the job's pieces as files in `in/`, prompted with her brief and a footer
code writes, and, once it stops, read back from `out/` alone: each file the bench's intake accepts becomes a file
piece, `RESULT.md` the summary. She never answers a dialog it is blocked on: the job becomes `blocked` and the person
answers where it runs. The runner closes the session once the job has ended, so nothing is left open in herdr.

`step` does one tick of one job and every write names the attempt, so a pod that dies between steps is retaken
(`BenchJobs.sweep`): a session already started is reused, files go up again under the same names, and the prompt is sent
again only when the session's state-change count has not moved since the start. Never logs a name, brief or summary."""

import logging
import mimetypes
from collections.abc import Mapping
from datetime import UTC, datetime

from .. import logs, services
from ..errands.bench_jobs import BenchJobs, Job, Outcome
from ..errands.jobs_config import CONFIG, JobsConfig
from ..files import config as files_config
from ..files.intake import Refused as FileRefused
from ..files.store import StoreUnavailable
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed, OutFile, Session
from ..workshop import bench_file, rules as workshop_rules
from ..workshop.model import Owner
from . import bench_job_bridge
from .bench_job_parts import NoSuchPiece, parts, fetch
from .tainted import her

log = logging.getLogger("ashley.tools")
RULES = workshop_rules.load()
RESULT = "RESULT.md"
TRANSIENT = ("busy", "unknown_state", "person_typing", "blocked")
REFUSED = ("bad_token", "wrong_person", "pin_mismatch")


Listed = Mapping[str, Session]
"""A person's sessions by id."""


async def listed_for(job: Job) -> Listed | None:
    """The sessions of the job's person, listed once for all their jobs of a tick; None when the bridge did not answer,
    which leaves each job to list for itself."""
    try:
        access = await bench_job_bridge.access_of(job.household_id, job.person_id)
        if access is None:
            return None
        return {s.id: s for s in (await services.get(Bridge).sessions(access)).sessions}
    except Exception:
        return None


def footer(config: JobsConfig = CONFIG) -> str:
    """What code adds to every brief: where the pieces are and where the results go."""
    return (f"\n\n---\nThe pieces this job gives you are files in ./in. Put what the person should get in ./out, at "
            f"most {config.max_outputs} files, and write ./out/{RESULT} as a summary of what you did and found, under "
            f"{config.result_chars} characters. Nothing outside ./out comes back.")


def directory(root: str, job: Job) -> str:
    return f"{root.rstrip('/')}/ashley-jobs/j{job.id}"


async def step(job: Job, listed: Listed | None = None, now: datetime | None = None,
               config: JobsConfig = CONFIG) -> Outcome | None:
    """One tick of `job` (claimed, `starting`, `running` or `blocked`): None while it goes on, else how it ended. A
    bridge that does not answer is not an ending: the job waits for it (`waiting`), and the deadline is what ends the job."""
    try:
        access = await bench_job_bridge.access_of(job.household_id, job.person_id)
    except Exception:
        return None
    if access is None:
        return Outcome("failed", "not_connected")
    late = job.deadline_at is not None and (now or datetime.now(UTC)) > job.deadline_at
    try:
        if job.state == "waiting":
            return await _wait(job, access, listed, late)
        if job.state == "starting":
            return await _start(job, access, config)
        return await _watch(job, access, listed, late, config)
    except BridgeFailed as e:
        logs.info(log, "bench_jobs.session_retry", job=job.id, attempt=job.attempts, reason=e.reason)
        if e.reason in REFUSED:
            return Outcome("failed", "bridge_refused")
        if e.reason == "herdr_unavailable" and job.state == "starting":
            if await services.get(BenchJobs).state(job.id, job.attempts, "waiting"):
                logs.info(log, "bench_jobs.waiting", job=job.id, attempt=job.attempts)
        return None


async def _wait(job: Job, access: Access, listed: Listed | None, late: bool) -> Outcome | None:
    """A `waiting` job: ended `failed` once past its deadline, else started again (`due`) when the bridge answers
    `sessions`. A bridge that does not answer raises BridgeFailed `herdr_unavailable`, which leaves it waiting."""
    if late:
        return Outcome("failed", "herdr_unavailable")
    if listed is None:
        await services.get(Bridge).sessions(access)
    if await services.get(BenchJobs).resume(job.id, job.attempts):
        logs.info(log, "bench_jobs.resumed", job=job.id, attempt=job.attempts)
    return None


async def _start(job: Job, access: Access, config: JobsConfig) -> Outcome | None:
    store = services.get(BenchJobs)
    bridge = services.get(Bridge)
    session_id, seq = job.session_id, job.session_seq
    if session_id is None:
        roots = (await bridge.sessions(access)).roots
        if not roots:
            return Outcome("failed", "no_roots")
        try:
            made = await bridge.start(access, directory(roots[0], job), f"job-{job.id}", None)
        except BridgeFailed as e:
            if e.reason in ("label_taken", "dir_not_allowed", "bad_request"):
                return Outcome("failed", e.reason)
            raise
        session_id, seq = made.id, made.seq
        if not await store.started(job.id, job.attempts, session_id, seq):
            await _close(access, session_id)
            return Outcome("cancelled", "stopped")
    if not await store.heartbeat(job.id, job.attempts):
        return Outcome("cancelled", "stopped")
    if job.prompted_at is None:
        refused = await _upload(job, access, session_id, config)
        if refused is not None:
            return refused
        if await _prompt(job, access, session_id, seq, config, job.session_id is not None) is False:
            return None
        await store.prompted(job.id, job.attempts)
    await store.state(job.id, job.attempts, "running")
    return None


async def _upload(job: Job, access: Access, session_id: str, config: JobsConfig) -> Outcome | None:
    try:
        given = await parts(Owner(job.household_id, job.person_id), job.bench_id, job.pieces, config)
    except NoSuchPiece:
        return Outcome("failed", "pieces_gone")
    sent = 0
    for part in given:
        data = await fetch(job.household_id, part)
        if data is None:
            return Outcome("failed", "file_missing")
        await services.get(Bridge).upload(access, session_id, part.name, data)
        sent += len(data)
    logs.info(log, "bench_jobs.uploaded", job=job.id, attempt=job.attempts, files=len(given), bytes=sent)
    return None


async def _prompt(job: Job, access: Access, session_id: str, seq: int | None, config: JobsConfig, resumed: bool) -> bool:
    """Whether the prompt is now sent (or was by an earlier attempt); False when the session is not ready for one yet.
    A `resumed` session, started by an earlier step, whose state-change count has moved was prompted already; with no
    count recorded, one that is no longer idle was."""
    now = {s.id: s for s in (await services.get(Bridge).sessions(access)).sessions}.get(session_id)
    if resumed and now is not None and (now.status != "idle" if seq is None else now.seq != seq):
        return True
    try:
        await services.get(Bridge).prompt(access, session_id, job.brief + footer(config))
    except BridgeFailed as e:
        if e.reason in TRANSIENT:
            return False
        if e.reason == "unconfirmed":
            return True
        raise
    return True


async def _watch(job: Job, access: Access, listed: Listed | None, late: bool,
                 config: JobsConfig) -> Outcome | None:
    store = services.get(BenchJobs)
    if job.session_id is None:
        return Outcome("failed", "session_lost")
    if listed is None:
        listed = {s.id: s for s in (await services.get(Bridge).sessions(access)).sessions}
    session = listed.get(job.session_id)
    if session is None:
        return Outcome("failed", "session_closed")
    if late:
        return await collect(job, access, "timed_out", config)
    if session.status == "blocked":
        await store.state(job.id, job.attempts, "blocked")
        return None
    if session.status == "done" or (session.status == "idle" and session.seq > (job.session_seq or 0)):
        return await collect(job, access, "done", config)
    await store.state(job.id, job.attempts, "running")
    return None


async def collect(job: Job, access: Access, ending: str, config: JobsConfig = CONFIG) -> Outcome:
    """Read `out/` as it stands: each file the intake takes (at most `max_outputs`) becomes a file piece, `RESULT.md`
    the summary, the rest counted refused. `ending` is `done` or `timed_out`."""
    assert job.session_id is not None
    bridge = services.get(Bridge)
    state = "timed_out" if ending == "timed_out" else "done"
    listed = await bridge.outputs(access, job.session_id)
    summary: str | None = None
    outputs: list[int] = []
    refused = 0
    limit = files_config.load().max_bytes
    for out in sorted(listed, key=lambda o: o.name):
        if out.name == RESULT:
            summary = await _summary(access, job.session_id, out, config)
        elif len(outputs) >= config.max_outputs:
            refused += 1
        else:
            piece = await _file(job, access, out, limit)
            if piece is None:
                refused += 1
            else:
                outputs.append(piece)
    logs.info(log, "bench_jobs.collected", job=job.id, attempt=job.attempts, files=len(listed), outputs=len(outputs),
              refused=refused)
    return Outcome("timed_out" if state == "timed_out" else "done", "deadline" if state == "timed_out" else None, summary,
                   tuple(outputs), refused)


async def _summary(access: Access, session_id: str, out: OutFile, config: JobsConfig) -> str | None:
    try:
        raw = await services.get(Bridge).download(access, session_id, out.name, config.result_chars * 4)
    except BridgeFailed:
        return None
    return raw.decode("utf-8", errors="replace").strip()[:config.result_chars] or None


async def _file(job: Job, access: Access, out: OutFile, limit: int) -> int | None:
    """The piece made of `out`'s file, None when it was not taken."""
    assert job.session_id is not None
    if out.bytes > limit:
        return None
    try:
        data = await services.get(Bridge).download(access, job.session_id, out.name, limit)
        _, applied = await bench_file.add_file(Owner(job.household_id, job.person_id), job.bench_id, her(), data,
                                               out.name, mimetypes.guess_type(out.name)[0] or "", RULES)
    except (BridgeFailed, FileRefused, StoreUnavailable):
        return None
    return applied.piece_id if applied.outcome == "accepted" else None


async def _close(access: Access, session_id: str) -> None:
    try:
        await services.get(Bridge).close(access, session_id)
    except BridgeFailed:
        logs.warning(log, "bench_jobs.close_failed")


async def close(job: Job) -> bool:
    """Close an ended job's session; True when it is closed or there is nothing to close or nothing will ever close it (the
    bridge refuses this connection), False when the bridge did not answer and it should be tried again."""
    if job.session_id is None:
        return True
    try:
        access = await bench_job_bridge.access_of(job.household_id, job.person_id)
        if access is not None:
            await services.get(Bridge).close(access, job.session_id)
    except BridgeFailed as e:
        return e.reason == "not_found" or e.reason in REFUSED
    except Exception:
        return False
    return True
