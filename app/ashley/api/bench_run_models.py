"""Wire models for running a bench's code piece (`api.bench_runs`) and for the latest run a piece shows
(`BenchPiece.last_run`)."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..runs.model import Artifact, Outcome, Output, Run
from ..text import NoNul
from ..workshop.model_report import report_of
from .bench_report_models import RunArtifact, RunReport, artifact_of, report_of_wire


class RunRequest(BaseModel):
    """Run piece `piece_id`, a code piece, as it is at `base_version` (the version the screen shows), in
    `run_language`, one of `WorkshopKinds.run_languages`."""

    model_config = ConfigDict(extra="forbid")

    piece_id: int
    base_version: int
    run_language: NoNul = Field(min_length=1, max_length=32)


class RunOutput(BaseModel):
    """What came out of a run. `run_outcome`: `ran` (to its end; `exit_code` is its status, non-zero included),
    `timed_out` (stopped at its deadline; what it printed until then is kept), `out_of_memory`, `failed` (nothing
    readable came back; nothing may have run) or `unknown` (it may have run, and what it printed was lost). `stdout`
    and `stderr` are cut to the sandbox's limit (`output_cut` says one was); `files` are the text files it left in its
    working directory, which the piece's next run starts with when it `ran`; `files_left_out` names the ones not kept.
    `artifacts` are the binary files a model run made and kept (empty for any other run), with download links; `report`
    is the report a model script wrote, each check judged by the app, null when the run left none."""

    run_outcome: Outcome
    exit_code: int | None
    stdout: str
    stderr: str
    output_cut: bool
    files: dict[str, str]
    files_left_out: list[str]
    artifacts: list[RunArtifact]
    report: RunReport | None


class PieceRun(BaseModel):
    """A piece's run: `run_id`, the `piece_version` it ran, when it started and finished, and its `run_output`, null
    until it is recorded: while it runs, and for good when its runner stopped part way (it is never run again)."""

    run_id: int
    piece_version: int
    started_at: datetime
    finished_at: datetime | None
    run_output: RunOutput | None


class RunApplied(BaseModel):
    """The Run command was accepted as `seq` and the piece was run as `run_id`: `run_output` is what came out. The
    bench read back shows it as the piece's `last_run`."""

    seq: int
    piece_id: int
    run_id: int
    run_output: RunOutput


def output_of(out: Output, household_id: int, artifacts: Sequence[Artifact], inputs: Mapping[str, str],
              key: bytes) -> RunOutput:
    """`out` of household `household_id`'s run as the wire shows it: its `artifacts` with links minted under `key`
    (empty: no link), and its report judged against the `inputs` the run started with."""
    found = report_of(out, inputs)
    return RunOutput(run_outcome=out.outcome, exit_code=out.exit_code, stdout=out.stdout, stderr=out.stderr,
                     output_cut=out.cut, files=dict(out.files), files_left_out=list(out.skipped),
                     artifacts=[artifact_of(household_id, a, key) for a in artifacts],
                     report=None if found is None else report_of_wire(found))


def piece_run_of(run: Run, key: bytes = b"") -> PieceRun:
    """A stored run of a bench's piece as the wire shows it, its artifacts' links minted under `key`."""
    assert run.bench is not None
    out = None if run.output is None else output_of(run.output, run.household_id, run.artifacts, run.files, key)
    return PieceRun(run_id=run.id, piece_version=run.bench.piece_version, started_at=run.started_at,
                    finished_at=run.finished_at, run_output=out)
