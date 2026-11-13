"""Running a code piece, for a person's press of Run and her `bench_run` alike: the `Run` command decided and logged
through `Workshop.apply`, then the piece's body run once through `ashley.runs.once.run_once`, recorded against that
command (and against her turn, when she ran it) and starting with the files the piece's last run left. When it has
finished, the owner's screens are told again (`BenchChanged`), so they read back what came out.

The command is logged before anything runs and the run is recorded before it starts, so a pod that stops part way
leaves either an accepted Run with no run (it never started) or a run with no output (it may have run); neither is
ever run again.

A run in `build123d` starts with the bench's measurements pieces merged as `measurements.json` (`measurements_file`) and the
print settings as `print.json` (`print_file`), and without the last run's `measurements.json`, `print.json`, `inputs.json`
and `out/report.json`, so a report read back after it is this run's. It is also handed the bench's STL, 3MF and STEP file pieces as binary inputs (`model_inputs`)."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .. import services
from ..live.events import BenchChanged, Shown
from ..live.live import Live
from ..runs import config as runs_config
from ..runs.config import RunsConfig
from ..runs.model import BenchRun, NewRun
from ..runs.once import Finished, run_once
from ..runs.runs import Runs, RunsUnavailable
from ..runs.sandbox import Sandbox
from . import measurements_file, model_inputs, print_file
from . import rules as workshop_rules
from .commands import Run
from .model import Owner, Piece
from .model_report import REPORT
from .rules import Rules
from .workshop import Applied, Workshop, WorkshopError

CONFIG = runs_config.load()
RULES = workshop_rules.load()
MODEL_LANGUAGE = "build123d"


class CannotRun(WorkshopError):
    """The run was refused before anything was logged: `why` is `language` (the sandbox does not run it), `blank`
    (the piece holds only whitespace) or `too_long` (longer than the sandbox's `max_script_chars`)."""

    def __init__(self, why: Literal["language", "blank", "too_long"]) -> None:
        super().__init__(why)
        self.why: Literal["language", "blank", "too_long"] = why


@dataclass(frozen=True)
class Asked:
    """Her turn that asked for the run: the conversation, the person turn and her tool call's id."""

    conversation_id: int
    turn_id: int
    call_id: str


@dataclass(frozen=True)
class PieceRun:
    """What a run of a piece came to: `applied`, the Run command as the bench decided it, and `finished`, the run,
    None when the command was refused or nothing was run after it was accepted (the run's start could not be
    recorded, or the piece changed between being read and the command being decided)."""

    applied: Applied
    finished: Finished | None


async def run_piece(owner: Owner, bench_id: int, command: Run, asked: Asked | None = None,
                    config: RunsConfig = CONFIG, rules: Rules = RULES, inputs: Sequence[int] | None = None) -> PieceRun:
    """Run piece `command.piece_id` of `owner`'s bench at `command.base_version`. Raises CannotRun before anything is
    logged (a piece the bench would refuse to run is not checked, and its refusal is logged); BenchNotFound,
    BenchClosed, WorkshopUnavailable and ValueError as `Workshop.apply`; InputRefused, before anything is logged, for a
    piece of `inputs` (the file pieces a model run is given; None is every model file on the bench, empty is none) that
    cannot be handed over; RunsUnavailable when the last run's files
    cannot be read, before anything is logged."""
    offered = services.get(Sandbox).languages()
    if command.language not in offered:
        raise CannotRun("language")
    language = offered[offered.index(command.language)]
    view = await services.get(Workshop).read(owner, bench_id)
    piece = next((p for p in view.pieces if p.id == command.piece_id and p.version == command.base_version), None)
    kind = None if piece is None else rules.kinds.get(piece.kind)
    if piece is not None and kind is not None and kind.format == "code":
        _check(piece, config)
    files = await services.get(Runs).files_left(owner.household_id, bench_id, command.piece_id)
    models = model_inputs.ModelInputs()
    if language == MODEL_LANGUAGE:
        files = _model_files(files, (p.text.body for p in view.pieces if _measures(p, rules)))
        profile = config.languages.get(MODEL_LANGUAGE)
        if profile is not None and profile.input_bytes:
            models = await model_inputs.inputs_of(owner.household_id, view.pieces, rules, profile.input_bytes, inputs)
        files = files if models.index is None else {**files, model_inputs.NAME: models.index}
    applied = await services.get(Workshop).apply(owner, bench_id, command)
    if applied.outcome != "accepted" or piece is None:
        return PieceRun(applied, None)
    turn = (None, None, None) if asked is None else (asked.conversation_id, asked.turn_id, asked.call_id)
    new = NewRun(owner.household_id, *turn, language=language, script=piece.text.body, files=files,
                 inputs=models.blobs, bench=BenchRun(bench_id, applied.seq, piece.id, piece.version))
    try:
        finished = await run_once(new)
    except RunsUnavailable:
        return PieceRun(applied, None)
    services.get(Live).publish(BenchChanged(Shown(owner.household_id, owner.person_id), bench_id, applied.seq,
                                                  "her" if command.by.person_id is None else "person"))
    return PieceRun(applied, finished)


def _check(piece: Piece, config: RunsConfig) -> None:
    if not piece.text.body.strip():
        raise CannotRun("blank")
    if len(piece.text.body) > config.max_script_chars:
        raise CannotRun("too_long")


def _measures(piece: Piece, rules: Rules) -> bool:
    kind = rules.kinds.get(piece.kind)
    return kind is not None and kind.format == "measurements"


def _model_files(left: Mapping[str, str], measurements: Iterable[str]) -> dict[str, str]:
    """`left`, the files the last run left, without that run's measurements, print settings, inputs index and report, and
    with the print settings and the bench's current measurements when it has any."""
    stale = (measurements_file.NAME, print_file.NAME, model_inputs.NAME, REPORT)
    files = {n: t for n, t in left.items() if n not in stale} | {print_file.NAME: print_file.file_text()}
    current = measurements_file.file_of(measurements)
    return files if current is None else {**files, measurements_file.NAME: current}
