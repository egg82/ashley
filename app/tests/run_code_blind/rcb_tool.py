"""Fakes for the run_code tool: a Sandbox that records the jobs it was given, and what the database held at the time."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ashley.runs.model import Artifact, Job, Language, NewRun, Output, Run
from ashley.runs.runs import Runs, RunsUnavailable
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.tools.run_code import RunCodeTools
from rcb_world import World

GIVES = Output("ran", 0, "OUT-ZQ", "ERR-ZQ", False, {"r.txt": "FILE-ZQ"}, ())


@dataclass
class Recording(Sandbox):
    result: Output | Exception = GIVES
    jobs: list[Job] = field(default_factory=lambda: list[Job]())
    during: Callable[[Job], None] = lambda job: None
    offers: tuple[Language, ...] = ("python",)

    def languages(self) -> tuple[Language, ...]:
        return self.offers

    async def run(self, job: Job) -> Output:
        self.jobs.append(job)
        self.during(job)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Unavailable(Recording):
    def __init__(self) -> None:
        super().__init__(SandboxUnavailable("down"))


def tools(w: World, turn: int | None = None) -> RunCodeTools:
    return RunCodeTools(w.home, w.conversation, w.turn if turn is None else turn)


class Wrapped(Runs):
    """The real Runs, with the named operations failing."""

    def __init__(self, inner: Runs, fail: set[str]) -> None:
        self.inner, self.fail = inner, fail

    async def start(self, run: NewRun) -> int:
        if "start" in self.fail:
            raise RunsUnavailable("down")
        return await self.inner.start(run)

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        if "finish" in self.fail:
            raise RunsUnavailable("down")
        return await self.inner.finish(run_id, output, artifacts)

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
