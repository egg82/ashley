"""An in-app worker for a bench job (`ashley.errands.bench_jobs`): a sub-agent of hers, `look_up`'s pattern, with the job's
bench tools behind `JobScope` and its own task, `bench_job`. It is given the brief and the pieces the job names, steps
until it returns a `JobResult`, and refreshes the job's claim before each step, which is also how it learns it was
cancelled. What crosses back is bounded here: the summary's length and the pieces it made. Its transcript is not kept.

Never logs a brief, title, piece or summary; `bench_jobs.agent_step` carries the job, attempt, round and duration."""

import logging
import time
from dataclasses import replace
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field

from .. import logs, services
from ..errands.bench_jobs import BenchJobs, Job, JobsUnavailable, Named, Outcome
from ..errands.jobs_config import CONFIG, JobsConfig
from ..inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ..inference.model import (DEFAULT_VARIANT, Entry, Message, Prompt, SystemPrompt, Task, ToolCalls, ToolChoice,
                               ToolResults)
from ..workshop.model import Owner
from . import cut
from .bench_files import BenchFileTools
from .bench_job_parts import NoSuchPiece, Part, parts
from .bench_run import BenchRunTools
from .bench_tools import BenchTools
from .composite import CompositeTools
from .job_scope import JobScope
from .tools import Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")
TASK: Task = "bench_job"


class JobResult(BaseModel):
    """The agent's last step. Every field is required, so the schema a model is sent states each."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    done: bool = Field(description="True when the brief is done; false when you stopped short of it.")
    summary: str = Field(description="What you made and found, in a few sentences for Ashley to tell the person, "
                                     "naming each piece by what it is (its id goes in pieces); when not done, what is "
                                     "missing.")
    pieces: list[int] = Field(description="The ids of the pieces you made that are the job's output; empty for none.")


def scope_of(job: Job) -> Tools:
    """The tools of one job: the bench's tools on its bench as its person, narrowed to the job's pieces."""
    inner = CompositeTools({
        "bench": BenchTools(job.household_id, job.person_id, job.bench_id),
        "run": BenchRunTools(job.household_id, job.person_id, job.bench_id, hand_off=False),
        "files": BenchFileTools(job.household_id, job.person_id, job.bench_id)})
    return JobScope(inner, job)


async def run(job: Job, config: JobsConfig = CONFIG) -> Outcome:
    """Run `job` (claimed, attempt `job.attempts`) to an outcome: `done` or `failed` with its reason, or `cancelled`
    when its claim was lost under it. Never raises for the model, the store or the bench being out of reach."""
    try:
        owner = Owner(job.household_id, job.person_id)
        given = await parts(owner, job.bench_id, job.pieces, config) + await _earlier(owner, job, config)
    except NoSuchPiece:
        return Outcome("failed", "pieces_gone")
    except Exception:
        return Outcome("failed", "unavailable")
    system = {DEFAULT_VARIANT: SystemPrompt(resources.files("ashley.tools").joinpath("bench_agent.md")
                                            .read_text(encoding="utf-8").strip())}
    tools = scope_of(job)
    try:
        return await _loop(job, tools, system, [Message("person", _first(job, given))], config)
    except (InferenceUnavailable, ToolsUnavailable):
        return Outcome("failed", "inference_unavailable")
    except InferenceRefused:
        return Outcome("failed", "refused")
    except JobsUnavailable:
        return Outcome("failed", "unavailable")


async def _earlier(owner: Owner, job: Job, config: JobsConfig) -> tuple[Part, ...]:
    """The pieces an earlier attempt made, as given pieces; one since removed is skipped."""
    named = {n.piece_id for n in job.pieces}
    found: list[Part] = []
    for made in job.made:
        if made not in named:
            try:
                found.extend(await parts(owner, job.bench_id, (Named(made),), config))
            except NoSuchPiece:
                continue
    return tuple(found)


async def _loop(job: Job, tools: Tools, system: dict[str, SystemPrompt], entries: list[Entry],
                config: JobsConfig) -> Outcome:
    specs = (await tools.catalogue()).specs
    for rounds in range(config.agent_max_tool_rounds + 1):
        if not await services.get(BenchJobs).heartbeat(job.id, job.attempts):
            return Outcome("cancelled", "stopped")
        started = time.monotonic()
        choice: ToolChoice = "auto" if rounds < config.agent_max_tool_rounds else "none"
        got = await services.get(Inference).step(TASK, Prompt(system, tuple(entries), specs, choice), JobResult)
        logs.info(log, "bench_jobs.agent_step", job=job.id, attempt=job.attempts, round=rounds,
                  duration_ms=int((time.monotonic() - started) * 1000))
        if isinstance(got, JobResult):
            return await _outcome(job, got, config)
        if choice == "none":
            break
        entries += [got, await _results(tools, got, config)]
    return Outcome("failed", "no_result")


async def _results(tools: Tools, asked: ToolCalls, config: JobsConfig) -> ToolResults:
    """Each call in the order asked, one at a time, each result cut to `tool_result_chars`."""
    out = [await tools.call(c) for c in asked.calls]
    return ToolResults(tuple(replace(r, content=_seen(r.content, config.tool_result_chars)) for r in out))


def _seen(content: str, limit: int) -> str:
    got = cut.visible(content, limit)
    return content if got is None else got.text


async def _outcome(job: Job, got: JobResult, config: JobsConfig) -> Outcome:
    now = await services.get(BenchJobs).get(job.household_id, job.person_id, job.id)
    made = set(job.made if now is None else now.made)
    named = tuple(p for p in dict.fromkeys(got.pieces) if p in made)
    outputs = named if named else tuple(sorted(made))
    return Outcome("done" if got.done else "failed", None if got.done else "not_done", got.summary[:config.result_chars],
                   outputs)


def _first(job: Job, given: tuple[Part, ...]) -> str:
    """The first message: the brief, then each piece the job names, whole when it is text, by name, type and size when
    it is bytes; and, for a retaken job, the pieces its earlier attempt made."""
    lines = [job.brief, ""]
    if job.made:
        lines += [f"An earlier attempt of this job already made pieces {', '.join(map(str, job.made))}; they are on "
                  "the bench to read and continue from.", ""]
    for p in given:
        if p.file is not None:
            lines += [f"Piece {p.piece_id} ({p.piece_kind}, a file of {p.file.media_type}, {p.size} bytes, "
                      f"named {p.file.name}); its bytes are not in this message.", ""]
        else:
            what = "a file its latest run kept" if p.origin == "run" else p.piece_kind
            lines += [f"Piece {p.piece_id} ({what}), titled {p.title}:", p.text or "", ""]
    return "\n".join(lines).strip()
