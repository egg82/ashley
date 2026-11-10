"""`run_code` (`ashley.tools.run_code.RunCodeTools`) and where a turn offers it (`channels.turn_tools.for_turn`): offered
only while the sandbox runs a language and the turn's ids are known; a change, so the tool loop never runs it twice;
every run recorded before it runs and again after; nothing runs unless its start was recorded; and what came out goes
back to her."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sandbox_support import CONFIG, Clock, FakeKube, Script
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolCall, ToolResult
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Artifact, Job, Language, NewRun, Output, Run
from ashley.runs.runs import Runs, RunsUnavailable
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.tools.everyday import HouseholdTools
from ashley.tools.run_code import NAME, RunCodeTools
from ashley.tools.tools import Catalogue, Tools

WEB = Inbound(household_id=10, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn")
EPOCH = datetime(2026, 10, 30, tzinfo=UTC)
OUT = Output("ran", 0, "3\n", "", False, {"out.txt": "3"}, ())


@dataclass
class Book(Runs):
    """Records what happens, in order, beside `Box`."""

    events: list[str]
    started: list[NewRun] = field(default_factory=list[NewRun])
    finished: list[tuple[int, Output]] = field(default_factory=list[tuple[int, Output]])
    down: bool = False
    finish_down: bool = False

    async def start(self, run: NewRun) -> int:
        if self.down:
            raise RunsUnavailable("down")
        self.events.append("start")
        self.started.append(run)
        return 41

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        if self.finish_down:
            raise RunsUnavailable("down")
        self.events.append("finish")
        self.finished.append((run_id, output))
        return Run(run_id, 10, 20, 30, "c1", "python", "", "", {}, EPOCH, EPOCH, output)

    async def get(self, household_id: int, run_id: int) -> Run | None:
        raise NotImplementedError

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        raise NotImplementedError

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        raise NotImplementedError

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        raise NotImplementedError

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        raise NotImplementedError


@dataclass
class Box(Sandbox):
    events: list[str]
    output: Output = OUT
    down: bool = False
    jobs: list[Job] = field(default_factory=list[Job])

    def languages(self) -> tuple[Language, ...]:
        return ("python",)

    async def run(self, job: Job) -> Output:
        self.events.append("run")
        self.jobs.append(job)
        if self.down:
            raise SandboxUnavailable("down")
        return self.output


class Everyday(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError


@pytest.fixture
def wired() -> tuple[Book, Box]:
    events: list[str] = []
    book, box = Book(events), Box(events)
    services.register(Tools, Everyday())
    services.register(Runs, book)
    services.register(Sandbox, box)
    return book, box


def call(arguments: dict[str, object]) -> ToolResult:
    tools = RunCodeTools(10, 20, 30)
    return asyncio.run(tools.call(ToolCall("c1", NAME, arguments)))


def names(tools: Tools) -> list[str]:
    return [s.name for s in asyncio.run(tools.catalogue()).specs]


def test_a_turn_with_its_ids_and_a_sandbox_offers_run_code_as_a_change(wired: tuple[Book, Box]) -> None:
    catalogue = asyncio.run(for_turn(WEB, (20, 30)).catalogue())
    spec = next(s for s in catalogue.specs if s.name == NAME)
    assert spec.reads is False
    assert json.dumps(spec.parameters["properties"]).count('"enum": ["python"]') == 1


def test_without_the_turn_ids_or_a_sandbox_it_is_not_offered(wired: tuple[Book, Box]) -> None:
    assert NAME not in names(for_turn(WEB))
    services.unregister(Sandbox)
    assert isinstance(for_turn(replace(WEB, speaker_id=None), (20, 30)), HouseholdTools)
    assert asyncio.run(RunCodeTools(10, 20, 30).catalogue()).specs == ()


def test_a_run_is_recorded_before_and_after_it_runs_and_its_output_returned(wired: tuple[Book, Box]) -> None:
    book, box = wired
    got = call({"language": "python", "script": "print(1+2)", "stdin": "in"})
    assert book.events == ["start", "run", "finish"]
    assert book.started == [NewRun(10, 20, 30, "c1", "python", "print(1+2)", "in")]
    assert box.jobs == [Job("run-41", "python", "print(1+2)", "in")]
    assert book.finished == [(41, OUT)]
    assert not got.is_error
    assert json.loads(got.content) == {"run_id": 41, "outcome": "ran", "exit_code": 0, "stdout": "3\n", "stderr": "",
                                       "output_cut": False, "files": {"out.txt": "3"}, "files_left_out": []}


def test_nothing_runs_when_its_start_cannot_be_recorded(wired: tuple[Book, Box]) -> None:
    book, box = wired
    book.down = True
    got = call({"language": "python", "script": "print(1)"})
    assert got.is_error and got.content.startswith("unavailable")
    assert box.jobs == []


def test_a_sandbox_that_cannot_run_it_is_an_error_and_recorded_as_failed(wired: tuple[Book, Box]) -> None:
    book, box = wired
    box.down = True
    got = call({"language": "python", "script": "print(1)"})
    assert got.is_error and got.content.startswith("unavailable")
    assert book.finished == [(41, Output("failed", None, "", ""))]


def test_an_output_that_cannot_be_recorded_still_reaches_her(wired: tuple[Book, Box]) -> None:
    book, _ = wired
    book.finish_down = True
    got = call({"language": "python", "script": "print(1)"})
    assert not got.is_error and json.loads(got.content)["stdout"] == "3\n"


@pytest.mark.parametrize("arguments", [
    {"language": "python"},
    {"language": "python", "script": "   "},
    {"language": "python", "script": "x" * 20_001},
    {"language": "ruby", "script": "puts 1"},
    {"language": "python", "script": "print(1)", "stdin": 3},
    {"language": "python", "script": "print(1)", "files": {"a": "b"}},
])
def test_bad_arguments_record_and_run_nothing(wired: tuple[Book, Box], arguments: dict[str, object]) -> None:
    book, _ = wired
    got = call(arguments)
    assert got.is_error and got.content.startswith("bad_arguments")
    assert book.events == []


def test_a_finished_run_whose_log_is_lost_closes_unknown_and_tells_her_so(wired: tuple[Book, Box],
                                                                         tmp_path: Path) -> None:
    book, _ = wired
    fake = FakeKube(tmp_path / "token", Script(log_status=500))
    clock = Clock()
    services.register(Sandbox, KubernetesSandbox(fake.api(), CONFIG, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock))
    got = call({"language": "python", "script": "print(1)"})
    assert book.finished == [(41, Output("unknown", None, "", ""))]
    assert not got.is_error
    result = json.loads(got.content)
    assert result["outcome"] == "unknown" and "output was lost" in result["note"]
