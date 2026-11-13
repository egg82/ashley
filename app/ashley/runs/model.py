"""What a code run is: the job a sandbox runs, what came out of it, and the record of one run tied to the turn that
asked for it, the bench command it was made by, or both."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Language = Literal["python", "build123d"]

Outcome = Literal["ran", "timed_out", "out_of_memory", "failed", "unknown"]
"""`ran`: the script ran to its end and `exit_code` is its status (non-zero included). `timed_out`: it ran past its
deadline and was stopped; what it printed until then is kept. `out_of_memory`: it was killed for memory. `failed`:
nothing readable came back. `unknown`: the pod was made but what became of it could not be learned (the API
stopped answering, or the pod or its log went missing); the script may have run."""


@dataclass(frozen=True)
class InputFile:
    """A binary file a job starts with, by reference: the object `household_id`/`sha256` in the object store
    (`ashley.files.intake.key_of`), `size` bytes. The bytes never pass through the job; the sandbox has them put where
    the script reads them."""

    household_id: int
    sha256: str
    size: int


@dataclass(frozen=True)
class Job:
    """One script to run. `stdin` is its standard input; `files` (name -> text) are in its working directory when it
    starts, and `inputs` (name -> InputFile) in its `inputs/`, read-only and never carried back. `name` is unique per run and safe as a Kubernetes name (`run-<id>`)."""

    name: str
    language: Language
    script: str
    stdin: str = ""
    files: Mapping[str, str] = field(default_factory=dict[str, str])
    inputs: Mapping[str, InputFile] = field(default_factory=dict[str, InputFile])


@dataclass(frozen=True)
class Output:
    """What came out of one run, each stream cut to the sandbox's limit (`cut` says one was). `exit_code` is None
    unless `outcome` is `ran`. `files` are the text files left in its working directory, within the file limits;
    `skipped` names the ones left out (binary, too large, or past the count). `artifacts` are the binary files a
    language's profile carries (`.glb`, `.stl`, `.3mf`), by name, within its `artifact_bytes`; empty for Python."""

    outcome: Outcome
    exit_code: int | None
    stdout: str
    stderr: str
    cut: bool = False
    files: Mapping[str, str] = field(default_factory=dict[str, str])
    skipped: tuple[str, ...] = ()
    artifacts: Mapping[str, bytes] = field(default_factory=dict[str, bytes])


@dataclass(frozen=True)
class Artifact:
    """A binary file a bench run made, kept in the object store (`ashley.files.intake.key_of(household, sha256)`): its
    `name` in the run's working directory, and the `size` and `media_type` its bytes were judged to have."""

    name: str
    sha256: str
    size: int
    media_type: str


@dataclass(frozen=True)
class BenchRun:
    """The bench command a run was made by: bench `bench_id`'s Run command `seq`, of piece `piece_id` at
    `piece_version`."""

    bench_id: int
    seq: int
    piece_id: int
    piece_version: int


@dataclass(frozen=True)
class NewRun:
    """A run about to start: the household; the conversation, person turn and tool call that asked for it (all three,
    or none for a run a person started on a bench); the job's language, script, input and files; and `bench`, the bench
    command it was made by, if any. Raises ValueError when only some of the turn's ids are given, or neither a turn
    nor a bench. `inputs` are the binary files the job starts with (`Job.inputs`); they are not recorded, so the record
    of a run that had some holds an index of them among its `files`."""

    household_id: int
    conversation_id: int | None
    turn_id: int | None
    call_id: str | None
    language: Language
    script: str
    stdin: str = ""
    files: Mapping[str, str] = field(default_factory=dict[str, str])
    bench: BenchRun | None = None
    inputs: Mapping[str, InputFile] = field(default_factory=dict[str, InputFile])

    def __post_init__(self) -> None:
        given = (self.conversation_id is not None, self.turn_id is not None, self.call_id is not None)
        if len(set(given)) != 1:
            raise ValueError("a run's conversation, turn and call are given together or not at all")
        if not given[0] and self.bench is None:
            raise ValueError("a run is asked for by a turn, a bench command, or both")


@dataclass(frozen=True)
class Run:
    """A stored run. `output` is None while it runs, and stays None for a run whose result was never recorded (its
    runner stopped mid-run; it is never run again). The turn's ids are None for a run a person started on a bench;
    `bench` is the bench command it was made by, if any; `artifacts` are the files of the output it kept."""

    id: int
    household_id: int
    conversation_id: int | None
    turn_id: int | None
    call_id: str | None
    language: Language
    script: str
    stdin: str
    files: Mapping[str, str]
    started_at: datetime
    finished_at: datetime | None
    output: Output | None
    bench: BenchRun | None = None
    artifacts: tuple[Artifact, ...] = ()
