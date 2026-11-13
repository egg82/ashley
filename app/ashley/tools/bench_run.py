"""Her runs of a bench's code pieces, for one turn of its talk (`channels.turn_tools`), offered while the sandbox runs
some language: `bench_run`, the person's Run made by her (`workshop.run_piece.run_piece`, recorded against her turn as
well as the bench), and `bench_last_run`, what a piece's latest run gave, whoever ran it, on the asker's own bench only. A run is a change (its spec
does not read), so the tool loop records it as started before it runs and never runs it again on resume."""

import time
from collections.abc import Mapping
from datetime import tzinfo
from typing import Any

from .. import services
from ..people.zone import zone_of
from ..stamp import stamp
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..errands.jobs_config import CONFIG as JOBS, JobsConfig
from ..runs.model import Language, Run
from ..runs.runs import Runs, RunsUnavailable
from ..runs.sandbox import Sandbox
from ..workshop import commands
from ..workshop.model import HER, Owner
from ..workshop.model_inputs import InputRefused
from ..workshop.run_piece import Asked, CannotRun, run_piece
from ..workshop.workshop import BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_results
from .bench_args import BadArguments, check_names, piece_id_of
from .run_code import result
from .run_model import extras
from .tools import Catalogue, Tools

RUN, LAST = "bench_run", "bench_last_run"
INSTRUCTIONS = ("To run a code piece of this bench, use bench_run on the version you read, not run_code: the person "
                "sees the run on the piece, and the files its last finished run left are in its working directory "
                "when it starts. bench_last_run shows what a piece's latest run gave, theirs included.")
CANNOT = {"language": "the sandbox does not run that language", "blank": "the piece holds no code to run",
          "too_long": "the piece is longer than the sandbox takes as one script"}
REFUSED = {"missing": "is not a piece of this bench", "not_model": "is not an STL, 3MF or STEP file piece",
           "too_large": "does not fit the size a run is given with the inputs named before it",
           "unavailable": "cannot be read from the store right now"}
HAND_OFF = ("this turn has made as many runs as it may: hand the rest to a worker with bench_hand_off, naming the pieces "
            "it needs, and say it is underway. Nothing ran")
LOST = "no result was recorded: it is still running, or its runner stopped and whether it ran is not known"


def specs(languages: tuple[Language, ...]) -> tuple[ToolSpec, ...]:
    piece: dict[str, object] = {"type": "integer"}
    return (
        ToolSpec(RUN, "Run a code piece of this bench once, as it is at the version you read, in a sandbox with no "
                 "network and no access to the house. Returns what it printed, its exit code and the text files it "
                 "left, which the piece's next run starts with. A model run (build123d) also returns the meshes it made "
                 "(artifacts) and its report, each check judged by the app: unconfirmed means a measurement it rests on "
                 "is guessed or missing; the app shows the person each guessed number one rests on, beside your reply, once. It is shown on the piece. A model run is given only the file pieces (STL, 3MF, STEP) "
                 "named in inputs, which existing(piece_id) reads; name just the ones the script uses, because they "
                 "share a size limit. Left out, inputs is every such file on the bench; an empty list is none. A piece "
                 "named that cannot be given refuses the run: nothing ran.",
                 {"type": "object", "properties": {"piece_id": piece, "base_version": {"type": "integer"},
                                                   "language": {"type": "string", "enum": list(languages)},
                                                   "inputs": {"type": "array", "items": piece}},
                  "required": ["piece_id", "base_version", "language"]}, outside=False, tier="runs"),
        ToolSpec(LAST, "What a piece's latest run gave, whoever ran it: the version it ran, what it printed, its exit "
                 "code and the files it left, and a model run's artifacts and report.", {"type": "object", "properties": {"piece_id": piece},
                                                "required": ["piece_id"]}, reads=True, outside=False),
    )


class BenchRunTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, conversation_id: int | None = None,
                 turn_id: int | None = None, hand_off: bool = True, config: JobsConfig = JOBS) -> None:
        """`conversation_id` and `turn_id` name the turn the runs are recorded against, and with `hand_off` (this turn
        can hand a job to a worker) bound its runs: past `max_runs_per_turn` the next is refused `hand_off`. A worker's
        tools name none, so its runs count against no turn."""
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._said = None if conversation_id is None or turn_id is None else (conversation_id, turn_id)
        self._hand_off = hand_off
        self._config = config

    async def catalogue(self) -> Catalogue:
        """Empty when the sandbox runs nothing."""
        languages = services.get(Sandbox).languages()
        return Catalogue(specs(languages), INSTRUCTIONS) if languages else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the sandbox or the model did: each is an error result, logged `tools.call`
        with the bench, piece, seq and run ids."""
        started = time.monotonic()
        spec = next((s for s in specs(services.get(Sandbox).languages()) if s.name == call.name), None)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, spec)
            return await (self._run(call, started) if call.name == RUN else self._last(call, started))
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except InputRefused as e:
            return bench_results.failed(call, started, "bad_inputs", f"input {e.piece} {REFUSED[e.why]}{f' ({e.sizes})' if e.sizes else ''}; "
                                        "nothing ran",
                                        bench=self._bench)
        except CannotRun as e:
            return bench_results.failed(call, started, "cannot_run", CANNOT[e.why], bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and runs nothing",
                                        bench=self._bench)
        except (WorkshopUnavailable, RunsUnavailable):
            return bench_results.failed(call, started, "unavailable", "the bench cannot be reached right now; "
                                        "nothing ran", bench=self._bench)

    async def _run(self, call: ToolCall, started: float) -> ToolResult:
        piece = piece_id_of(call.arguments)
        version, language = call.arguments.get("base_version"), call.arguments.get("language")
        if type(version) is not int or not isinstance(language, str):
            raise BadArguments("base_version is an integer and language a string")
        if await self._capped():
            return bench_results.failed(call, started, "hand_off", HAND_OFF, bench=self._bench, piece=piece)
        got = await run_piece(self._owner, self._bench, commands.Run(HER, piece, version, language),
                              None if self._said is None else Asked(*self._said, call.id),
                              inputs=_inputs_of(call.arguments))
        applied, done = got.applied, got.finished
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command="run", seq=applied.seq, piece=piece)
        if done is None or not done.reached:
            return bench_results.failed(call, started, "unavailable", "code cannot be run right now; nothing ran",
                                        bench=self._bench, seq=applied.seq, piece=piece)
        body = {"seq": applied.seq, "piece_id": piece, "version": version, **result(done.run_id, done.output),
                **extras(done.artifacts, done.output, done.inputs)}
        return bench_results.ok(call, started, body, bench=self._bench, command="run", seq=applied.seq, piece=piece,
                                run=done.run_id, outcome_of_run=done.output.outcome)

    async def _capped(self) -> bool:
        """Whether this turn has made as many bench runs as it may, counted from the record so a resume on another pod
        counts the same."""
        if not self._hand_off or self._said is None:
            return False
        made = await services.get(Runs).bench_runs_in_turn(self._owner.household_id, self._said[1])
        return made >= self._config.max_runs_per_turn

    async def _last(self, call: ToolCall, started: float) -> ToolResult:
        piece = piece_id_of(call.arguments)
        await services.get(Workshop).read(self._owner, self._bench)
        last = (await services.get(Runs).last_on_bench(self._owner.household_id, self._bench)).get(piece)
        if last is None or last.bench is None:
            return bench_results.ok(call, started, {"piece_id": piece, "run": None}, bench=self._bench, piece=piece)
        return bench_results.ok(call, started, {"piece_id": piece, **_last_run(last, await zone_of(self._owner.household_id))}, bench=self._bench,
                                piece=piece, run=last.id)


def _inputs_of(args: Mapping[str, object]) -> list[int] | None:
    named: Any = args.get("inputs")
    if named is None:
        return None
    if named.__class__ is not list:
        raise BadArguments("inputs is a list of piece ids")
    ids: list[int] = [n for n in named if type(n) is int]
    if len(ids) != len(named):
        raise BadArguments("inputs is a list of piece ids")
    return ids


def _last_run(run: Run, zone: tzinfo | None) -> dict[str, object]:
    assert run.bench is not None
    ran = {**({} if zone is None else {"ran_at": stamp(run.started_at, zone)}), "version": run.bench.piece_version, "by": "you" if run.turn_id is not None else "the person"}
    if run.output is None:
        return {**ran, "run_id": run.id, "outcome": None, "note": LOST}
    return {**ran, **result(run.id, run.output), **extras(run.artifacts, run.output, run.files)}
