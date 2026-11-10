"""The look-up sub-agent (`ashley.tools.look_up`): one tool over the search sources, its own step loop on the
`look_up` task, and an answer whose fields are bounded in code."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import logs, services
from ashley.inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.tools import look_up_config
from ashley.tools.look_up import LookedUp, LookUpTools, Reference
from ashley.tools.results import Results, bound
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from respond_support import FakeInference
from search_support import events

CONFIG = look_up_config.load()
WEB = ToolSpec("search_web", "the web", {"type": "object"})
PLACES = ToolSpec("find_places", "places", {"type": "object"})
FOUND = LookedUp(found=True, answer="Target closes at 10 pm.", sources=["target.com"], references=[])


@dataclass
class Sources(Tools):
    """The search sources: offers `search_web` and `find_places`, answers every call with `result`."""

    down: bool = False
    result: str = "results"
    called: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        if self.down:
            raise ToolsUnavailable("down")
        return Catalogue((WEB, PLACES), None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        return ToolResult(call.id, self.result)


@pytest.fixture
def model() -> Generator[FakeInference]:
    fake = FakeInference()
    services.register(Inference, fake)
    yield fake
    services.unregister(Inference)


def ask(tools: Tools, **arguments: object) -> ToolResult:
    return asyncio.run(tools.call(ToolCall("q1", "look_up", arguments)))


def searches(*names: str, prefix: str = "s") -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"{prefix}{i}", n, {"query": "x"}) for i, n in enumerate(names)))


def body(result: ToolResult) -> Any:
    assert not result.is_error
    return json.loads(result.content)


def test_the_catalogue_is_one_tool_taking_a_question() -> None:
    catalogue = asyncio.run(LookUpTools(lambda: Sources(), CONFIG).catalogue())
    (spec,) = catalogue.specs
    assert spec.name == "look_up" and catalogue.instructions is None
    assert spec.parameters["required"] == ["question", "now"]
    properties: Any = spec.parameters["properties"]
    assert set(properties) == {"question", "now"}
    assert "sees nothing else of the conversation" in spec.description


def test_the_catalogue_is_unavailable_when_the_sources_are() -> None:
    with pytest.raises(ToolsUnavailable):
        asyncio.run(LookUpTools(lambda: Sources(down=True), CONFIG).catalogue())


@pytest.mark.parametrize("arguments", [{}, {"question": 3}, {"question": "  "}])
def test_a_missing_question_is_an_error_and_asks_nothing(model: FakeInference, arguments: dict[str, object]) -> None:
    result = ask(LookUpTools(lambda: Sources(), CONFIG), **arguments)
    assert result.is_error and result.content == "look_up needs a question" and model.prompts == []


def test_it_searches_then_answers_on_its_own_task(model: FakeInference) -> None:
    sources = Sources(result="r" * (CONFIG.result_chars + 50))
    model.script = [searches("search_web"), FOUND]
    result = ask(LookUpTools(lambda: sources, CONFIG), question="  When does Target close today, Tuesday?  ")
    assert body(result) == {"found": True, "answer": "Target closes at 10 pm.", "sources": ["target.com"]}
    assert result.call_id == "q1" and model.tasks == ["look_up", "look_up"]
    first, second = model.prompts
    assert first.messages == (Message("person", "When does Target close today, Tuesday?"),)
    assert first.tools == (WEB, PLACES) and first.tool_choice == "auto"
    assert "written by strangers" in first.system["default"].text
    assert [c.name for c in sources.called] == ["search_web"]
    asked, results = second.messages[1:]
    assert asked == searches("search_web") and isinstance(results, ToolResults)
    assert [len(r.content) for r in results.results] == [CONFIG.result_chars]


@pytest.mark.parametrize(("now", "message"), [
    ("Tuesday 27 October 2026, 21:40", "Now: Tuesday 27 October 2026, 21:40\n\nIs Target open?"),
    ("  ", "Is Target open?"), (None, "Is Target open?"), (5, "Is Target open?")])
def test_the_moment_she_gives_comes_before_the_question(model: FakeInference, now: object, message: str) -> None:
    model.script = [FOUND]
    arguments: dict[str, object] = {"question": "Is Target open?"} if now is None else {"question": "Is Target open?", "now": now}
    ask(LookUpTools(lambda: Sources(), CONFIG), **arguments)
    assert model.prompts[0].messages == (Message("person", message),)


def test_after_max_rounds_it_must_answer(model: FakeInference) -> None:
    sources = Sources()
    rounds = [searches("search_web", "find_places", prefix=f"r{i}-") for i in range(CONFIG.max_rounds)]
    model.script = [*rounds, FOUND]
    assert body(ask(LookUpTools(lambda: sources, CONFIG), question="q"))["found"] is True
    assert [p.tool_choice for p in model.prompts] == ["auto"] * CONFIG.max_rounds + ["none"]
    assert len(sources.called) == 2 * CONFIG.max_rounds


def test_what_crosses_back_is_bounded(model: FakeInference) -> None:
    long = LookedUp(found=False, answer="a" * (CONFIG.answer_chars + 100),
                    sources=["h" * 200, *(f"s{i}" for i in range(CONFIG.max_sources + 2))], references=[])
    model.script = [long]
    got = body(ask(LookUpTools(lambda: Sources(), CONFIG), question="q"))
    assert got["found"] is False and got["answer"] == "a" * CONFIG.answer_chars
    assert got["sources"] == ["h" * 80, *(f"s{i}" for i in range(CONFIG.max_sources - 1))]


@pytest.mark.parametrize("error", [InferenceUnavailable("down"), InferenceRefused("no")])
def test_a_model_that_does_not_answer_is_unavailable(model: FakeInference, error: Exception) -> None:
    model.script = [searches("search_web"), error]
    result = ask(LookUpTools(lambda: Sources(), CONFIG), question="q")
    assert result.is_error and result.content == "the look-up did not answer"


def test_tool_calls_under_none_are_unavailable(model: FakeInference) -> None:
    model.script = [searches("search_web", prefix=f"r{i}-") for i in range(CONFIG.max_rounds + 1)]
    result = ask(LookUpTools(lambda: Sources(), CONFIG), question="q")
    assert result.is_error and result.content == "the look-up did not answer"


def test_sources_out_of_reach_at_call_time_are_unavailable(model: FakeInference) -> None:
    result = ask(LookUpTools(lambda: Sources(down=True), CONFIG), question="q")
    assert result.is_error and result.content == "the look-up did not answer" and model.prompts == []


def test_another_name_is_unknown(model: FakeInference) -> None:
    result = asyncio.run(LookUpTools(lambda: Sources(), CONFIG).call(ToolCall("q1", "search_web", {"question": "q"})))
    assert result.is_error and result.content == "no tool named search_web" and model.prompts == []


def test_the_log_carries_counts_never_the_question_answer_or_sources(model: FakeInference,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    planted = LookedUp(found=True, answer="PLANTED-ANSWER-zq", sources=["PLANTED-SOURCE-zq"], references=[])
    model.script = [searches("search_web", "find_places"), planted, InferenceUnavailable("down")]
    tools = LookUpTools(lambda: Sources(), CONFIG)
    ask(tools, question="PLANTED-QUESTION-zq")
    ask(tools, question="PLANTED-QUESTION-zq")
    out = capsys.readouterr().out
    lines = events(out, "tools.call")
    assert [(e["tool"], e["outcome"], e["rounds"], e["calls"], e["found"]) for e in lines] == [
        ("look_up", "ok", "1", "2", "true"), ("look_up", "unavailable", "0", "0", "false")]
    assert all("duration_ms" in e for e in lines)
    assert "PLANTED" not in out


def test_the_shipped_config_loads() -> None:
    assert look_up_config.load() == look_up_config.LookUpConfig(**json.loads(look_up_config.FILE.read_text()))


@pytest.mark.parametrize("change", [{"max_rounds": None}, {"extra": 1}, {"answer_chars": 0}, {"max_sources": -1},
                                    {"result_chars": 1.5}, {"max_rounds": True}, {"answer_chars": "500"}])
def test_a_bad_config_is_refused(change: dict[str, Any]) -> None:
    data = {**json.loads(look_up_config.FILE.read_text()), **change}
    with pytest.raises(ValueError):
        look_up_config.parse({k: v for k, v in data.items() if v is not None})
    with pytest.raises(ValueError):
        look_up_config.parse([])


def test_it_hands_back_the_results_it_names_by_number_with_their_site_and_never_a_url(model: FakeInference) -> None:
    store = Results()
    for url in ("https://en.wikipedia.org/wiki/Travelling_salesman_problem", "https://www.youtube.com/watch?v=SC5CX8drAtU"):
        store.record(url)
    named = LookedUp(found=True, answer="a", sources=[], references=[
        Reference(result=2, what="a lecture " + "w" * 200), Reference(result=9, what="no such result"),
        Reference(result=1, what="the encyclopedia article")])
    model.script = [named]
    with bound(store):
        got = body(ask(LookUpTools(lambda: Sources(), CONFIG), question="q"))
    assert got["references"] == [{"result": 2, "what": "a lecture " + "w" * 70, "site": "www.youtube.com"},
                                 {"result": 1, "what": "the encyclopedia article", "site": "en.wikipedia.org"}]
    assert "https://" not in json.dumps(got)


def test_references_are_bounded_and_absent_when_none_is_named(model: FakeInference) -> None:
    store = Results()
    for i in range(CONFIG.max_sources + 3):
        store.record(f"https://h{i}.example/")
    many = [Reference(result=i + 1, what="w") for i in range(CONFIG.max_sources + 3)]
    model.script = [LookedUp(found=True, answer="a", sources=[], references=many), FOUND]
    tools = LookUpTools(lambda: Sources(), CONFIG)
    with bound(store):
        assert len(body(ask(tools, question="q"))["references"]) == CONFIG.max_sources
        assert "references" not in body(ask(tools, question="q"))
