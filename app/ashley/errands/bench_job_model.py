"""What the BenchJobs store takes and hands out."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Worker = Literal["agent", "claude_code"]
WORKERS: tuple[Worker, ...] = ("agent", "claude_code")
State = Literal["due", "waiting", "starting", "running", "blocked", "done", "failed", "timed_out", "cancelled"]
FINAL: tuple[State, ...] = ("done", "failed", "timed_out", "cancelled")
Ending = Literal["done", "failed", "timed_out", "cancelled"]


@dataclass(frozen=True)
class Named:
    """A piece of the bench a worker is given: `run_files` adds the files its latest run kept."""

    piece_id: int
    run_files: bool = False


@dataclass(frozen=True)
class NewJob:
    """A job to record `due`, or `waiting` when the person's machine was not answering at hand-off: asked in turn `turn` of `conversation` by `person` on `bench`, whose `job` piece is
    `piece_id`. `title` and `brief` are people's data and are never logged."""

    household: int
    person: int
    bench: int
    conversation: int
    turn: int
    worker: Worker
    title: str
    brief: str
    pieces: tuple[Named, ...]
    piece_id: int
    waiting: bool = False


@dataclass(frozen=True)
class Outcome:
    """How a job ended: `reason` a slug when it did not finish well, `summary` what the worker says it did, `outputs`
    the pieces it made that the person should look at, `refused` how many files it returned that were not taken."""

    state: Ending
    reason: str | None = None
    summary: str | None = None
    outputs: tuple[int, ...] = ()
    refused: int = 0


@dataclass(frozen=True)
class Job:
    """One job as stored. `attempts` is how many times it has been claimed; `made` the pieces its worker added, across
    attempts. `session_id` and `prompted_at` are a Claude Code job's progress through `starting`, `session_seq` the session's
    state-change count when it was started."""

    id: int
    household_id: int
    person_id: int
    bench_id: int
    conversation_id: int
    turn_id: int
    group_id: int
    worker: Worker
    title: str
    brief: str
    pieces: tuple[Named, ...]
    made: tuple[int, ...]
    piece_id: int
    state: State
    attempts: int
    session_id: str | None
    session_seq: int | None
    prompted_at: datetime | None
    created_at: datetime
    deadline_at: datetime | None
    finished_at: datetime | None
    reason: str | None
    summary: str | None
    outputs: tuple[int, ...]
    refused: int

    @property
    def final(self) -> bool:
        return self.state in FINAL


@dataclass(frozen=True)
class Counts:
    """What a sweep did: `retaken` jobs whose claim lapsed and went back to `due`, `failed` ones that had used every
    attempt, `timed_out` ones of a group past its timeout."""

    retaken: int
    failed: int
    timed_out: int
