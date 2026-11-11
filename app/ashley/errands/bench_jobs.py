"""The BenchJobs service (`ashley.services`): jobs she hands to a worker from a bench (`decisions.md`, "She hands a bench
job to workers and stays with the person"). A job is `due`, then `running` (a Claude Code job passes through `starting`
first), may be `blocked` on the person or `waiting` for their machine to answer, and ends `done`, `failed`, `timed_out` or `cancelled`. A Claude Code
job is `done` only once its worker has written `out/RESULT.md`; a session that goes idle without one is prompted once to
finish, and a job that reaches its deadline without one ends `timed_out` with reason `no_result`. Jobs started together
form a group, which settles when every job of it is final.

Every method that changes a claimed job takes the `attempt` it was claimed at and changes nothing, answering False,
when the row is no longer at that attempt or is already final, so a late worker cannot overwrite a sweep's or a
cancel's verdict. Titles and briefs are people's data, stored and never logged."""

from abc import abstractmethod
from datetime import datetime
from typing import Literal

from ..services import Service
from .bench_job_model import (FINAL as FINAL, Counts as Counts, Ending as Ending, Job as Job, Named as Named,
                              NewJob as NewJob, Outcome as Outcome, State as State, WORKERS as WORKERS, Worker as Worker)


class JobsUnavailable(Exception):
    """The store could not be reached or written. Transient."""


class BenchJobs(Service):
    @classmethod
    def null(cls) -> "BenchJobs":
        return NullBenchJobs()

    @abstractmethod
    async def start_group(self, jobs: tuple[NewJob, ...]) -> tuple[int, tuple[int, ...]]:
        """Store every job `due` in one transaction under one new group; the group id and the job ids in order. Raises
        JobsUnavailable."""

    @abstractmethod
    async def start(self, job: NewJob) -> int:
        """A group of the one job; its id. Raises JobsUnavailable."""

    @abstractmethod
    async def running(self, household_id: int, person_id: int, worker: Worker) -> int:
        """How many of the person's jobs of `worker` are not final. Raises JobsUnavailable."""

    @abstractmethod
    async def claim(self, worker: Worker, claim_s: float) -> Job | None:
        """In one transaction take the oldest `due` job of `worker`, `FOR UPDATE SKIP LOCKED`: `running` (`starting`
        for claude_code), `attempts + 1`, `claimed_at` now, and its deadline set when it is the first claim; None when
        there is none. `claim_s` is how long the claim holds before `sweep` calls it lapsed. Raises JobsUnavailable."""

    @abstractmethod
    async def active(self, worker: Worker) -> tuple[Job, ...]:
        """The `worker`'s jobs that are `waiting`, `starting`, `running` or `blocked`, oldest first. Raises JobsUnavailable."""

    @abstractmethod
    async def unfinished(self) -> tuple[Job, ...]:
        """Every job that is not final, oldest first. Raises JobsUnavailable."""

    @abstractmethod
    async def heartbeat(self, job_id: int, attempt: int) -> bool:
        """Refresh `claimed_at`; False when the job is no longer claimed at `attempt` (it was cancelled, swept or
        finished), which tells the worker to stop. Raises JobsUnavailable."""

    @abstractmethod
    async def made(self, job_id: int, attempt: int, piece_id: int) -> bool:
        """Record that the worker added piece `piece_id`, once. Raises JobsUnavailable."""

    @abstractmethod
    async def started(self, job_id: int, attempt: int, session_id: str, seq: int | None = None) -> bool:
        """Record the Claude Code session the job runs in, and its state-change count `seq` as it was started when
        known, which a retake compares to know whether a prompt reached it. Raises JobsUnavailable."""

    @abstractmethod
    async def prompted(self, job_id: int, attempt: int) -> bool:
        """Record that the session was prompted. Raises JobsUnavailable."""

    @abstractmethod
    async def idle(self, job_id: int, attempt: int, now: datetime) -> datetime:
        """Record that the session is idle without a result and return when it was first seen so: `now` unless an earlier
        tick already recorded it. Raises JobsUnavailable."""

    @abstractmethod
    async def busy(self, job_id: int, attempt: int) -> bool:
        """Forget that the session was idle, because it works again. Raises JobsUnavailable."""

    @abstractmethod
    async def nudged(self, job_id: int, attempt: int) -> bool:
        """Record that the session was prompted to finish; False when it already was or the job is not live at
        `attempt`. Raises JobsUnavailable."""

    @abstractmethod
    async def state(self, job_id: int, attempt: int, state: Literal["running", "blocked", "waiting"]) -> bool:
        """Move a Claude Code job between `running` and `blocked` (from `starting`, to `running`), or from `starting` to
        `waiting` when the person's machine did not answer. Raises JobsUnavailable."""

    @abstractmethod
    async def resume(self, job_id: int, attempt: int) -> bool:
        """Put a `waiting` job back to `due`, to be claimed and started again; False when it is no longer `waiting` at
        `attempt`. Raises JobsUnavailable."""

    @abstractmethod
    async def finish(self, job_id: int, attempt: int, outcome: Outcome) -> bool:
        """End the job as `outcome` says. Raises JobsUnavailable."""

    @abstractmethod
    async def cancel(self, household_id: int, person_id: int, job_id: int) -> bool:
        """End the person's job `cancelled`; False when it is not theirs or is already final. Raises
        JobsUnavailable."""

    @abstractmethod
    async def due_closes(self) -> tuple[Job, ...]:
        """The ended Claude Code jobs (`done`, `failed`, `timed_out` or `cancelled`) that started a session which has not been
        closed yet, oldest first. A job ends only after its outputs are collected, so closing the session loses nothing.
        Raises JobsUnavailable."""

    @abstractmethod
    async def closed(self, job_id: int) -> None:
        """Record that an ended job's session is closed. Raises JobsUnavailable."""

    @abstractmethod
    async def sweep(self, claim_s: float, now: datetime | None = None) -> Counts:
        """Jobs `running` (agent) or `starting` whose claim is more than `claim_s` before `now` go back to `due`, or
        `failed` with reason `attempts` once they have used `max_attempts`; unfinished jobs of a group created more
        than `group_timeout_min` before `now` end `timed_out`. Raises JobsUnavailable."""

    @abstractmethod
    async def get(self, household_id: int, person_id: int, job_id: int) -> Job | None:
        """The person's job; None when it is not theirs. Raises JobsUnavailable."""

    @abstractmethod
    async def group(self, household_id: int, person_id: int, group_id: int) -> tuple[Job, ...]:
        """The person's jobs of the group, in id order. Raises JobsUnavailable."""

    @abstractmethod
    async def group_settled(self, group_id: int) -> tuple[Job, ...] | None:
        """Every job of the group when each is final, else None; None too for a group nothing is in. Raises
        JobsUnavailable."""


class NullBenchJobs(BenchJobs):
    """What an unwired process sees: every call raises, so nothing is started or taken by mistake."""

    async def start_group(self, jobs: tuple[NewJob, ...]) -> tuple[int, tuple[int, ...]]:
        raise JobsUnavailable("bench jobs are not wired")

    async def start(self, job: NewJob) -> int:
        raise JobsUnavailable("bench jobs are not wired")

    async def running(self, household_id: int, person_id: int, worker: Worker) -> int:
        raise JobsUnavailable("bench jobs are not wired")

    async def claim(self, worker: Worker, claim_s: float) -> Job | None:
        raise JobsUnavailable("bench jobs are not wired")

    async def active(self, worker: Worker) -> tuple[Job, ...]:
        raise JobsUnavailable("bench jobs are not wired")

    async def unfinished(self) -> tuple[Job, ...]:
        raise JobsUnavailable("bench jobs are not wired")

    async def heartbeat(self, job_id: int, attempt: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def made(self, job_id: int, attempt: int, piece_id: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def started(self, job_id: int, attempt: int, session_id: str, seq: int | None = None) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def prompted(self, job_id: int, attempt: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def idle(self, job_id: int, attempt: int, now: datetime) -> datetime:
        raise JobsUnavailable("bench jobs are not wired")

    async def busy(self, job_id: int, attempt: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def nudged(self, job_id: int, attempt: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def state(self, job_id: int, attempt: int, state: Literal["running", "blocked", "waiting"]) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def resume(self, job_id: int, attempt: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def finish(self, job_id: int, attempt: int, outcome: Outcome) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def cancel(self, household_id: int, person_id: int, job_id: int) -> bool:
        raise JobsUnavailable("bench jobs are not wired")

    async def due_closes(self) -> tuple[Job, ...]:
        raise JobsUnavailable("bench jobs are not wired")

    async def closed(self, job_id: int) -> None:
        raise JobsUnavailable("bench jobs are not wired")

    async def sweep(self, claim_s: float, now: datetime | None = None) -> Counts:
        raise JobsUnavailable("bench jobs are not wired")

    async def get(self, household_id: int, person_id: int, job_id: int) -> Job | None:
        raise JobsUnavailable("bench jobs are not wired")

    async def group(self, household_id: int, person_id: int, group_id: int) -> tuple[Job, ...]:
        raise JobsUnavailable("bench jobs are not wired")

    async def group_settled(self, group_id: int) -> tuple[Job, ...] | None:
        raise JobsUnavailable("bench jobs are not wired")
