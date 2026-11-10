"""One code run, the one way any caller runs a script: recorded in `Runs` as started, run once in the locator's
`Sandbox`, and recorded again with what came out. Nothing runs unless its start was recorded."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from .. import logs, services
from .artifacts import keep
from .model import Artifact, Job, NewRun, Output
from .runs import Runs, RunsUnavailable
from .sandbox import Sandbox, SandboxUnavailable

log = logging.getLogger("ashley.runs")


@dataclass(frozen=True)
class Finished:
    """Run `run_id` ended with `output`. `reached` is False when the sandbox could not run it at all (the output is
    then `failed` with nothing printed, and nothing ran). `artifacts` are the output's binary files kept in the object
    store (a bench run's only); `output.artifacts` is then empty. `inputs` are the files the script started with."""

    run_id: int
    output: Output
    reached: bool = True
    artifacts: tuple[Artifact, ...] = ()
    inputs: Mapping[str, str] = field(default_factory=dict[str, str])


async def run_once(new: NewRun) -> Finished:
    """Record `new` as started, run it as job `run-<id>` with its files, keep the artifacts of a bench run
    (`artifacts.keep`), and record what came out. Raises
    RunsUnavailable, or ValueError for text Postgres cannot store, when the start could not be recorded: nothing ran.
    An output that cannot be recorded is still returned, logged `runs.unrecorded`."""
    run_id = await services.get(Runs).start(new)
    try:
        output = await services.get(Sandbox).run(Job(f"run-{run_id}", new.language, new.script, new.stdin, new.files, new.inputs))
    except SandboxUnavailable:
        failed = Output("failed", None, "", "")
        await _finish(run_id, failed)
        return Finished(run_id, failed, reached=False)
    output, artifacts = await keep(new, run_id, output)
    await _finish(run_id, output, artifacts)
    return Finished(run_id, output, artifacts=artifacts, inputs=new.files)


async def _finish(run_id: int, output: Output, artifacts: tuple[Artifact, ...] = ()) -> None:
    try:
        await services.get(Runs).finish(run_id, output, artifacts)
    except (RunsUnavailable, ValueError, KeyError) as e:
        logs.warning(log, "runs.unrecorded", run=run_id, error=type(e).__name__)
