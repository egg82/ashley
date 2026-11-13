"""`send_readers` (`ashley.tools.readers`): the readers of one call run at once, each report is cut to length in code, a
reader reads with only the tools of hers that change nothing, and the result taints the turn exactly when a reader that
answered read outside words."""

import asyncio
import json
from collections.abc import Generator, Mapping
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.model import Message, Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.tools.composite import CompositeTools
from ashley.tools.only import Only
from ashley.tools.outside import Outside
from ashley.tools.readers import NAME, ReaderReport, ReaderTools
from ashley.tools.readers_config import ReadersConfig
from ashley.tools.reading import Reading
from ashley.tools.tools import Catalogue, Tools
from respond_support import FakeInference, T

CONFIG = ReadersConfig(max_readers=3, max_rounds=2, result_chars=4000, report_chars=200)
INBOX = ToolSpec("inbox_read", "mail", {"type": "object"}, reads=True, outside=True)
CALENDAR = ToolSpec("calendar_read", "calendar", {"type": "object"}, reads=True, outside=False)
SEND = ToolSpec("mail_send", "send", {"type": "object"}, outside=False, tier="runs")
WEB = Inbound(household_id=10, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn")


@dataclass
class Box(Tools):
    """Her sources: an inbox (outside words), a calendar (none) and sending mail (a change). With `meet`, a call to the
    inbox or the calendar waits until the other has started."""

    meet: bool = False
    called: list[str] = field(default_factory=list[str])
    started: dict[str, asyncio.Event] = field(default_factory=dict[str, asyncio.Event])

    async def catalogue(self) -> Catalogue:
        return Catalogue((INBOX, CALENDAR, SEND), None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call.name)
        if self.meet:
            self.started.setdefault(call.name, asyncio.Event()).set()
            other = "calendar_read" if call.name == "inbox_read" else "inbox_read"
            await self.started.setdefault(other, asyncio.Event()).wait()
        return ToolResult(call.id, f"{call.name}: three items")


@dataclass
class Readers(FakeInference):
    """Each reader by its brief: first it calls the tool its brief names (`brief` -> tool), then it reports `report`
    (`brief` -> text), or raises when the brief maps to an exception."""

    calls: Mapping[str, str] = field(default_factory=dict[str, str])
    reports: Mapping[str, str | Exception] = field(default_factory=dict[str, str | Exception])

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.prompts.append(prompt)
        self.tasks.append(task)
        first = prompt.messages[0]
        assert isinstance(first, Message)
        brief = first.text.split("\n\n")[-1]
        if not isinstance(prompt.messages[-1], ToolResults) and brief in self.calls:
            return ToolCalls((ToolCall(f"{brief}-1", self.calls[brief], {}),))
        report = self.reports[brief]
        if isinstance(report, Exception):
            raise report
        return output.model_validate(ReaderReport(found=True, report=report).model_dump())


@pytest.fixture
def box() -> Box:
    return Box()


def readers_over(box: Tools) -> ReaderTools:
    return ReaderTools(lambda names: Reading(Only(box, names)), CONFIG)


def wire(model: Readers) -> None:
    services.register(Inference, model)


@pytest.fixture(autouse=True)
def unwire() -> Generator[None]:
    yield
    services.unregister(Inference)


def send(tools: Tools, *readers: tuple[str, list[str]]) -> ToolResult:
    arguments = {"readers": [{"brief": b, "tools": t} for b, t in readers], "now": "Friday 09:00"}
    return asyncio.run(tools.call(ToolCall("r1", NAME, arguments)))


def reports(result: ToolResult) -> list[dict[str, object]]:
    return json.loads(result.content)["readers"]


def test_the_readers_of_one_call_run_at_once_and_report_in_the_order_sent() -> None:
    box = Box(meet=True)
    wire(Readers(calls={"mail": "inbox_read", "week": "calendar_read"}, reports={"mail": "two bills", "week": "dentist"}))

    async def both() -> ToolResult:
        return await asyncio.wait_for(readers_over(box).call(ToolCall("r1", NAME, {
            "readers": [{"brief": "mail", "tools": ["inbox_read"]}, {"brief": "week", "tools": ["calendar_read"]}],
            "now": "Friday 09:00"})), 1.0)

    got = asyncio.run(both())
    assert not got.is_error and sorted(box.called) == ["calendar_read", "inbox_read"]
    assert reports(got) == [{"found": True, "report": "two bills"}, {"found": True, "report": "dentist"}]


def test_a_report_longer_than_report_chars_is_cut_and_says_so(box: Box) -> None:
    wire(Readers(reports={"mail": "x" * 1000, "week": "short"}))
    got = reports(send(readers_over(box), ("mail", ["inbox_read"]), ("week", ["calendar_read"])))
    first, second = str(got[0]["report"]), got[1]["report"]
    assert len(first) <= CONFIG.report_chars and first.startswith("[cut:") and first.endswith("x")
    assert second == "short"


def test_more_readers_than_max_readers_is_an_error_and_sends_none(box: Box) -> None:
    model = Readers(reports={"a": "r"})
    wire(model)
    got = send(readers_over(box), *[("a", ["inbox_read"])] * (CONFIG.max_readers + 1))
    assert got.is_error and model.prompts == [] and box.called == []
    assert not send(readers_over(box), *[("a", ["inbox_read"])] * CONFIG.max_readers).is_error


@pytest.mark.parametrize("readers", [[], [{"brief": "", "tools": []}], [{"brief": "a"}], ["a"], "a"])
def test_readers_that_are_not_briefs_with_tool_names_are_an_error(box: Box, readers: object) -> None:
    got = asyncio.run(readers_over(box).call(ToolCall("r1", NAME, {"readers": readers, "now": "x"})))
    assert got.is_error


def test_through_her_turns_tools_a_reader_is_offered_only_the_named_reads_and_cannot_call_a_change(box: Box) -> None:
    services.register(Tools, box)
    model = Readers(calls={"mail": "mail_send"}, reports={"mail": "sent nothing"})
    wire(model)
    turn = for_turn(replace(WEB, speaker_id=1))
    assert NAME in [s.name for s in asyncio.run(turn.catalogue()).specs]
    got = send(turn, ("mail", ["inbox_read", "mail_send"]))
    assert [t.name for t in model.prompts[0].tools] == ["inbox_read"]
    assert reports(got) == [{"found": True, "report": "sent nothing"}]
    assert box.called == []
    services.unregister(Tools)


def test_a_reader_reads_only_with_what_the_turn_allows_when_a_reminder_names_its_tools(box: Box) -> None:
    services.register(Tools, box)
    model = Readers(calls={"week": "calendar_read"}, reports={"week": "dentist"})
    wire(model)
    turn = for_turn(replace(WEB, tools_only=(NAME, "calendar_read")))
    reports(send(turn, ("week", ["inbox_read", "calendar_read"])))
    assert [t.name for t in model.prompts[0].tools] == ["calendar_read"] and box.called == ["calendar_read"]
    services.unregister(Tools)


def test_a_reader_given_no_tool_of_hers_that_reads_reports_an_error_without_a_model(box: Box) -> None:
    model = Readers(reports={})
    wire(model)
    got = reports(send(readers_over(box), ("mail", ["mail_send", "no_such_tool"])))
    assert list(got[0]) == ["error"] and model.prompts == []


def tainted_by(box: Box, *readers: tuple[str, list[str]], model: Readers) -> tuple[ToolResult, str | None]:
    wire(model)
    outside = Outside(CompositeTools({"readers": readers_over(box)}), None, None)
    got = asyncio.run(outside.call(ToolCall("r1", NAME, {
        "readers": [{"brief": b, "tools": t} for b, t in readers], "now": "x"})))
    return got, outside.tainted


def test_a_reader_that_read_outside_words_taints_the_turn(box: Box) -> None:
    got, tainted = tainted_by(box, ("week", ["calendar_read"]), ("mail", ["inbox_read"]),
                              model=Readers(calls={"mail": "inbox_read", "week": "calendar_read"},
                                            reports={"mail": "bills", "week": "dentist"}))
    assert got.outside is True and tainted == NAME


def test_readers_that_read_only_household_words_leave_the_turn_untainted(box: Box) -> None:
    got, tainted = tainted_by(box, ("week", ["calendar_read"]),
                              model=Readers(calls={"week": "calendar_read"}, reports={"week": "dentist"}))
    assert box.called == ["calendar_read"] and got.outside is False and tainted is None


def test_a_reader_that_read_outside_words_but_did_not_answer_brings_nothing_back_and_does_not_taint(box: Box) -> None:
    got, tainted = tainted_by(box, ("mail", ["inbox_read"]), ("week", ["calendar_read"]),
                              model=Readers(calls={"mail": "inbox_read", "week": "calendar_read"},
                                            reports={"mail": InferenceUnavailable("down"), "week": "dentist"}))
    assert box.called.count("inbox_read") == 1 and list(reports(got)[0]) == ["error"]
    assert got.outside is False and tainted is None
