"""What the bench replay eval (`evals.bench_replay`) stands a bench on: the real Workshop, Runs and Sandbox of a scratch
database, with the captured file bytes in a store in memory. A logged command is applied again as it was decided (a run
executed for real when asked), the person's reactions are read as the wake sweep reads them, and every finished run's
report is kept as it finishes, since finishing a bench run prunes the piece's older runs. It sits here because only
`tools` may reach the workshop's, the runs' and the files' types."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .. import services
from ..files.intake import key_of
from ..files.memory import MemoryStore
from ..files.store import ObjectStore
from ..looks.looker import Looker
from ..runs import config as runs_config
from ..runs.model import Artifact, NewRun, Output, Run
from ..runs.podman import PodmanSandbox
from ..runs.sandbox import Sandbox
from ..runs.runs import Runs, RunsUnavailable
from ..workshop import commands
from ..workshop.codec import decode_command
from ..workshop.model import By, Owner
from ..workshop.model_inputs import InputRefused
from ..workshop.model_report import report_of
from ..workshop.reactions import Unseen
from ..workshop.run_piece import CannotRun, run_piece
from ..workshop.workshop import Workshop


async def file_bytes(household_id: int, sha256: str) -> bytes | None:
    """A file's bytes from the wired object store."""
    return await services.get(ObjectStore).get(key_of(household_id, sha256))


def install_files(household_id: int, files: Mapping[str, bytes]) -> None:
    """Make a store in memory holding `files` (sha256 -> bytes) under `household_id` the process's ObjectStore."""
    store = MemoryStore()
    store.objects.update({key_of(household_id, sha): data for sha, data in files.items()})
    services.register(ObjectStore, store)


def record_runs() -> "RecordingRuns":
    """Wrap the wired Runs so every finished bench run's report is kept, and make the wrapper the process's Runs."""
    recording = RecordingRuns(services.get(Runs))
    services.register(Runs, recording)
    return recording


def local_sandbox(cad_image: str) -> None:
    """Run code in podman containers on this machine, build123d in `cad_image` (pinned by digest; ValueError)."""
    services.register(Sandbox, PodmanSandbox(runs_config.load().with_image("build123d", cad_image)))


def no_screens() -> None:
    """Leave no browser wired: a replay's bench lives in a scratch database no look pod can reach, so only an image
    piece can be looked at."""
    services.unregister(Looker)


async def open_bench(household_id: int, person_id: int, title: str, work: str | None) -> int:
    owner = Owner(household_id, person_id)
    bench = await services.get(Workshop).open(owner, title)
    if work is not None:
        await services.get(Workshop).set_work(owner, bench.id, work)
    return bench.id


async def apply(household_id: int, person_id: int, bench_id: int, raw: Mapping[str, Any], by_person: bool,
                outside: bool, execute: bool, current: bool = False) -> str:
    """Apply the logged command `raw` again, made by the bench's person when `by_person` and by her otherwise; a run is
    executed in the sandbox when `execute` (and only logged when not), of the piece as it stands now when `current`
    (a replayed bench's versions are not the logged ones). Returns the outcome: the decision's, or for an executed run
    that never ran, `cannot_run`, `bad_inputs` or `unavailable` (the sandbox could not run it)."""
    owner = Owner(household_id, person_id)
    command = decode_command(dict(raw), By(person_id if by_person else None, outside))
    if current and isinstance(command, commands.Run):
        view = await services.get(Workshop).read(owner, bench_id)
        now = next((p.version for p in view.pieces if p.id == command.piece_id), command.base_version)
        command = replace(command, base_version=now)
    if not execute or not isinstance(command, commands.Run):
        return (await services.get(Workshop).apply(owner, bench_id, command)).outcome
    try:
        got = await run_piece(owner, bench_id, command)
    except CannotRun:
        return "cannot_run"
    except InputRefused:
        return "bad_inputs"
    except RunsUnavailable:
        return "unavailable"
    if got.applied.outcome == "accepted" and (got.finished is None or not got.finished.reached):
        return "unavailable"
    return got.applied.outcome


async def unseen(household_id: int, bench_id: int) -> Unseen | None:
    """The person's changes on the bench she has not reacted to, with no pause asked."""
    found = await services.get(Workshop).unseen(0.0, 50, 30)
    return next((u for u in found if u.household_id == household_id and u.bench_id == bench_id), None)


async def reacted(unseen: Unseen) -> None:
    await services.get(Workshop).reacted(unseen.household_id, unseen.bench_id, unseen.to_seq, 604800.0)


@dataclass(frozen=True)
class Finished:
    """One finished bench run as its report judged it: None counts when it left no report it could read."""

    seq: int
    piece_id: int
    version: int
    started: float
    finished: float
    outcome: str
    exit_code: int | None
    checks: int | None
    failed: int | None
    overlaps: int | None
    turn_id: int | None


@dataclass
class RecordingRuns(Runs):
    """`inner`, keeping each finished bench run in `finished` as it finishes."""

    inner: Runs
    finished: list[Finished] = field(default_factory=list[Finished])

    async def start(self, run: NewRun) -> int:
        return await self.inner.start(run)

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        done = await self.inner.finish(run_id, output, artifacts)
        if done.bench is not None:
            self.finished.append(_finished(done, output))
        return done

    async def get(self, household_id: int, run_id: int) -> Run | None:
        return await self.inner.get(household_id, run_id)

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        return await self.inner.in_conversation(household_id, conversation_id)

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        return await self.inner.of_turns(household_id, turn_ids, latest)

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        return await self.inner.last_on_bench(household_id, bench_id)

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        return await self.inner.files_left(household_id, bench_id, piece_id)


def _finished(run: Run, output: Output) -> Finished:
    assert run.bench is not None
    report = report_of(output, run.files)
    ended = run.finished_at or run.started_at
    return Finished(run.bench.seq, run.bench.piece_id, run.bench.piece_version, run.started_at.timestamp(),
                    ended.timestamp(), output.outcome, output.exit_code,
                    None if report is None else len(report.checks),
                    None if report is None else sum(c.verdict == "fail" for c in report.checks),
                    None if report is None else len(report.overlaps), run.turn_id)
