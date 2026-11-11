"""Her hand-off of a bench job (`ashley.errands.bench_jobs`): `bench_hand_off` gives one to three jobs to workers and
returns at once, `bench_job_cancel` stops one the person no longer wants. Offered per bench turn by
`ashley.channels.turn_tools.sources`, where the reply reaches the speaker alone and nobody is waiting on the turn. All
the jobs of a call are checked before any is recorded. Arguments, titles and briefs are never logged; `tools.call` carries
the outcome, counts and the reason."""

import time

from ..errands.bench_jobs import JobsUnavailable
from ..errands.jobs_config import CONFIG, JobsConfig
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..workshop import rules as workshop_rules
from ..workshop.model import Owner
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from . import bench_job_args, bench_job_bridge, bench_job_cancel, bench_job_start, bench_results
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

RULES = workshop_rules.load()
HAND_OFF, CANCEL = "bench_hand_off", "bench_job_cancel"
INSTRUCTIONS = (
    "A job that takes many runs or a long loop is not done in your own turn: bench_hand_off gives up to three jobs to "
    "workers, each written as a brief that stands alone, with the ids of the pieces it needs and nothing else of the "
    "bench, which is all a worker sees. It returns at once and each job shows on the bench as its own card; say in "
    "plain words what is underway and go on talking. A worker adds pieces and changes only its own, so jobs of one "
    "call cannot collide, and you are woken once, when the last of them ends, to reconcile what they made and act on "
    "it. The worker `agent` does a job with bench tools alone, in a few minutes; `claude_code`, when offered, "
    "runs a session on the person's own machine, for repositories, many files, tools the bench lacks or work that takes "
    "longer. A bench turn makes only a couple of runs of its own, and the next is refused: that is the point at which "
    "the loop becomes a job. A claude_code brief keeps all of the work inside its job folder, since nothing outside it comes back. If a result says watched is false, tell the person you could not arm the watch. If it says "
    "waiting is true, the person's machine is not answering: tell them the claude_code job is waiting for it, starts by "
    "itself when it answers and ends as failed if it does not in time, and that you will be told either way. "
    "bench_job_cancel stops a job when the person asks.")
HINTS = {
    "no_such_piece": "a piece named is not on this bench's layout (unknown, on the shelf, or another bench's); "
                     "bench_read lists the ids. Nothing was started",
    "too_many": "the person already has as many jobs of that worker running as are allowed; wait for them to end. "
                "Nothing was started",
    "too_large": "the pieces named, with their runs' files if asked, are more, or larger, than a worker is given: name fewer, or "
                 "only the ones it needs. "
                 "Nothing was started",
    "not_connected": "the person has not connected their Claude Code bridge, so claude_code is not possible; use agent "
                     "or tell them. Nothing was started",
    "bridge_too_old": "their bridge is too old to take files: tell them to update it. Nothing was started",
    "no_roots": "their bridge was set up with no folder to start a session under: tell them. Nothing was started",
    "bridge_refused": "their bridge answered and refused this connection (its token, person or certificate no longer "
                      "match): tell them to connect it again. Nothing was started",
    "unavailable": "the bench or the jobs cannot be reached right now. Nothing was started",
}


def specs(can_code: bool, config: JobsConfig = CONFIG) -> tuple[ToolSpec, ...]:
    workers = ["agent", "claude_code"] if can_code else ["agent"]
    piece = {"type": "object", "required": ["id"], "properties": {
        "id": {"type": "integer", "description": "A piece of this bench's layout."},
        "run_files": {"type": "boolean", "description": "Also give the files the piece's latest run kept and made (for a "
                                                         "model: the STL, 3MF and GLB). A model script that reads other "
                                                         "pieces' meshes (inputs.json lists them) needs those pieces "
                                                         "named too."}}}
    job = {"type": "object", "required": ["worker", "title", "brief", "pieces"], "properties": {
        "worker": {"type": "string", "enum": workers},
        "title": {"type": "string", "description": "A few words for the person's job card."},
        "brief": {"type": "string", "description": f"What to do and what to hand back, whole, at most {config.brief_chars} "
                                                   "characters; the worker sees nothing else of the conversation."},
        "pieces": {"type": "array", "items": piece, "description": "The pieces this job is given; empty for none."}}}
    return (
        ToolSpec(HAND_OFF, f"Hand one to {config.max_group} jobs to workers and go on talking. Returns the group, each "
                 "job's id and piece, and whether the watch that wakes you when they all end is armed.",
                 {"type": "object", "required": ["jobs"], "properties": {"jobs": {"type": "array", "items": job}}},
                 outside=False, tier="runs"),
        ToolSpec(CANCEL, "Stop a job: its piece shows it cancelled and its worker stops.",
                 {"type": "object", "required": ["job"], "properties": {"job": {"type": "integer"}}},
                 outside=False, tier="runs"))


class BenchJobTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, said: tuple[int, int], can_code: bool,
                 config: JobsConfig = CONFIG) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._said = said
        self._can_code = can_code
        self._config = config

    async def catalogue(self) -> Catalogue:
        return Catalogue(specs(self._can_code, self._config), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the store or the model did: each is an error result."""
        started = time.monotonic()
        spec = next((s for s in specs(self._can_code, self._config) if s.name == call.name), None)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, spec)
            return await (self._hand_off(call, started) if call.name == HAND_OFF else self._cancel(call, started))
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except bench_job_start.Refused as e:
            return bench_results.failed(call, started, e.reason, HINTS[e.reason], bench=self._bench)
        except bench_job_bridge.NotReady as e:
            return bench_results.failed(call, started, e.reason, HINTS[e.reason], bench=self._bench)
        except (BenchNotFound, BenchClosed, WorkshopUnavailable, JobsUnavailable):
            return bench_results.failed(call, started, "unavailable", HINTS["unavailable"], bench=self._bench)

    async def _hand_off(self, call: ToolCall, started: float) -> ToolResult:
        drafts = bench_job_args.drafts(call.arguments, self._config, self._can_code, RULES.title_max_chars)
        waiting = False
        if any(d.worker == "claude_code" for d in drafts):
            try:
                await bench_job_bridge.ready(self._owner.household_id, self._owner.person_id)
            except bench_job_bridge.NotReady as e:
                if e.reason != "herdr_unavailable":
                    raise
                waiting = True
        await bench_job_start.check(self._owner, self._bench, drafts, self._config)
        made = await bench_job_start.start(self._owner, self._bench, self._said, drafts, waiting)
        waits = sum(j.state == "waiting" for j in made.jobs)
        body: dict[str, object] = {"group": made.group, "watched": made.watched, "waiting": waits > 0,
                                   "jobs": [{"job": j.id, "piece": j.piece_id, "worker": j.worker, "state": j.state}
                                            for j in made.jobs]}
        return bench_results.ok(call, started, body, bench=self._bench, group=made.group, jobs=len(made.jobs),
                                watched=made.watched, waiting=waits)

    async def _cancel(self, call: ToolCall, started: float) -> ToolResult:
        job = await bench_job_cancel.cancel(self._owner, _job_id(call))
        if job is None:
            return bench_results.failed(call, started, "no_such_job", "the person has no job with that id",
                                        bench=self._bench)
        return bench_results.ok(call, started, {"job": job.id, "state": job.state}, bench=self._bench, job=job.id,
                                state=job.state)


def _job_id(call: ToolCall) -> int:
    job = call.arguments.get("job")
    if type(job) is not int:
        raise BadArguments("job is a whole number")
    return job
