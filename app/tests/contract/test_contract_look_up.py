"""`look_up`: the sub-agent Ashley calls as one tool. The catalogue, the question errors, the loop it runs (task, system
prompt, one question, the inner tools only, `auto` for `max_rounds` rounds then `none`, results cut), the JSON it
returns with its caps, how an unavailable or refusing model ends, the log line and what it never carries, the shipped
`look_up.json`, the persona's account of an unreachable `search`, and the task's routes."""

import dataclasses
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, get_args

import pytest
from ashley import logs, services
from ashley.inference import routes
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, Task, ToolCalls, ToolResult, ToolResults
from ashley.persona import facts
from ashley.persona.persona import system
from ashley.tools import look_up as look_up_module
from ashley.tools import look_up_config
from ashley.tools.look_up import LookedUp, LookUpTools
from ashley.tools.look_up_config import LookUpConfig, load
from ashley.tools.tools import Tools, ToolsUnavailable
from conversations_support import events
from look_up_contract_support import (CONFIG, MARK, PLACES, WEB, Brain, Sources, answer, ask, cfg, look_up, reply,
                                      results_of)
from search_contract_support import Stub, run
from test_contract_persona import CONTEXT

QUESTION = "does Target close early on Sundays?"
NEEDS = "look_up needs a question"
SILENT = "the look-up did not answer"
PROMPT_FILE = Path(look_up_module.__file__).with_name("look_up.md")


def test_the_catalogue_is_one_tool_with_a_required_question() -> None:
    c = run(LookUpTools(lambda: Sources(), CONFIG).catalogue())
    (tool,) = c.specs
    assert tool.name == "look_up" and c.instructions is None
    assert tool.parameters["type"] == "object" and tool.parameters["required"] == ["question", "now"]
    properties: Any = tool.parameters["properties"]
    assert set(properties) == {"question", "now"}
    assert properties["question"]["type"] == properties["now"]["type"] == "string"
    assert "web" in tool.description.lower() and "place" in tool.description.lower()


def test_the_catalogue_raises_when_the_inner_sources_do() -> None:
    async def scenario() -> None:
        with pytest.raises(ToolsUnavailable):
            await LookUpTools(lambda: Sources(down=True), CONFIG).catalogue()

    run(scenario())


@pytest.mark.parametrize("arguments", [{}, {"question": None}, {"question": 7}, {"question": ["a"]}, {"question": ""},
                                       {"question": " \n\t "}, {"query": QUESTION}])
def test_a_missing_or_blank_question_is_an_error_and_asks_nobody(arguments: dict[str, object]) -> None:
    brain, sources = Brain(), Sources()
    result = look_up(brain, sources=sources, arguments=arguments)
    assert result == ToolResult("k1", NEEDS, is_error=True)
    assert brain.seen == [] and sources.called == []


def test_a_real_question_is_not_a_question_error() -> None:
    assert look_up(Brain([answer()])).is_error is False, "control: the same call with a question works"


def test_another_tool_name_is_an_error_and_asks_nobody() -> None:
    brain = Brain([answer()])
    result = look_up(brain, name="search_web", arguments={"query": "x"})
    assert result.call_id == "k1" and result.is_error and brain.seen == []


def test_the_first_step_is_the_look_up_task_with_the_prompt_file_and_one_question() -> None:
    brain = Brain([answer()])
    look_up(brain, QUESTION)
    (step,) = brain.seen
    assert step.task == "look_up" and step.output is LookedUp and step.conversation_id is None
    assert PROMPT_FILE.read_text().strip() and set(step.prompt.system) >= {"default"}
    assert step.prompt.system_for("default").text.strip() == PROMPT_FILE.read_text().strip()
    assert step.prompt.messages == (Message("person", QUESTION),)


def test_the_inner_tools_are_offered_under_auto_and_ashleys_are_not() -> None:
    house = Stub("house", ("lights_on", "unlock_door"))
    services.register(Tools, house)
    try:
        brain = Brain([answer()])
        look_up(brain)
    finally:
        services.unregister(Tools)
    (step,) = brain.seen
    assert step.prompt.tools == (WEB, PLACES) and step.prompt.tool_choice == "auto"
    assert house.called == [] and house.catalogues == 0


def test_a_round_runs_each_call_through_the_sources_and_sends_the_results_back_in_order() -> None:
    brain, sources = Brain([ask("find_places", "search_web"), answer()]), Sources()
    reply_ = reply(look_up(brain, sources=sources))
    asked = ask("find_places", "search_web")
    assert sources.called == list(asked.calls)
    first, second = brain.seen
    assert second.prompt.messages == (Message("person", QUESTION), asked,
                                      ToolResults((ToolResult("c0", "result:find_places"),
                                                   ToolResult("c1", "result:search_web"))))
    assert second.prompt.tools == first.prompt.tools and reply_["found"] is True


def test_a_result_is_cut_to_result_chars_with_the_cut_said_and_a_shorter_one_is_not() -> None:
    sources = Sources({"search_web": ("x" * 400, False), "find_places": ("y" * 300, True)})
    brain = Brain([ask("search_web", "find_places"), answer()])
    look_up(brain, sources=sources, config=cfg(result_chars=300))
    a, b = results_of(brain.seen[1].prompt).results
    assert len(a.content) <= 300 and a.content.startswith("[cut: only the first") and "of 400 characters" in a.content
    assert b == ToolResult("c1", "y" * 300, is_error=True)
    brain = Brain([ask("search_web"), answer()])
    look_up(brain, sources=Sources({"search_web": ("z" * 25, False)}), config=cfg(result_chars=25))
    assert results_of(brain.seen[1].prompt).results[0].content == "z" * 25


@pytest.mark.parametrize("rounds", [1, 2, 3])
def test_auto_for_max_rounds_rounds_then_none_and_the_loop_ends(rounds: int) -> None:
    brain, sources = Brain(repeat=("search_web",)), Sources()
    result = look_up(brain, sources=sources, config=cfg(max_rounds=rounds))
    assert brain.tool_choices == ["auto"] * rounds + ["none"], "control: the model asked every time it could"
    assert len(sources.called) == rounds
    assert reply(result)["answer"] == "gave up" and not result.is_error
    assert all(s.task == "look_up" and s.prompt.tools == (WEB, PLACES) for s in brain.seen)


def test_an_answer_before_the_cap_ends_the_loop_there() -> None:
    brain = Brain([ask("search_web"), ask("find_places"), answer()], repeat=("search_web",))
    look_up(brain)
    assert brain.tool_choices == ["auto", "auto", "auto"]


def test_the_result_is_json_of_the_reply_with_nothing_added() -> None:
    result = look_up(Brain([answer("Open until nine.", True, ["pinecrestmarket.example", "Pinecrest Market Eastside"])]))
    assert result.call_id == "k1" and not result.is_error
    assert json.loads(result.content) == {"found": True, "answer": "Open until nine.",
                                          "sources": ["pinecrestmarket.example", "Pinecrest Market Eastside"]}


def test_not_found_is_still_a_result_not_an_error() -> None:
    result = look_up(Brain([answer("Only a 2019 post.", False, [])]))
    assert not result.is_error and json.loads(result.content) == {"found": False, "answer": "Only a 2019 post.",
                                                                  "sources": []}


def test_the_answer_is_cut_to_answer_chars_and_one_that_fits_is_not() -> None:
    assert reply(look_up(Brain([answer("a" * 70)]), config=cfg(answer_chars=40)))["answer"] == "a" * 40
    assert reply(look_up(Brain([answer("b" * 40)]), config=cfg(answer_chars=40)))["answer"] == "b" * 40
    assert reply(look_up(Brain([answer("c" * 600)])))["answer"] == "c" * 500


def test_sources_are_cut_to_max_sources_in_order_and_each_to_80_chars() -> None:
    names = ["a" * 100, "b" * 80, "c" * 79, "d", "e"]
    got = reply(look_up(Brain([answer(sources=names)]), config=cfg(max_sources=4)))["sources"]
    assert got == ["a" * 80, "b" * 80, "c" * 79, "d"]
    assert reply(look_up(Brain([answer(sources=names[:2])])))["sources"] == ["a" * 80, "b" * 80]
    assert len(reply(look_up(Brain([answer(sources=names)])))["sources"]) == 3


@pytest.mark.parametrize("error", [InferenceUnavailable("no route"), InferenceRefused("declined")])
@pytest.mark.parametrize("script", [[], [ask("search_web")]], ids=["first_step", "after_a_round"])
def test_an_unavailable_or_refusing_model_is_unavailable_and_never_raises(error: Exception, script: list[Any]) -> None:
    result = look_up(Brain([*script, error]))
    assert result == ToolResult("k1", SILENT, is_error=True)


def logged(capsys: pytest.CaptureFixture[str], brain: Brain, **kw: Any) -> tuple[ToolResult, list[dict[str, str]], str]:
    logs.setup()
    capsys.readouterr()
    result = look_up(brain, **kw)
    out = capsys.readouterr().out
    return result, events(out, "tools.call"), out


def test_an_ok_call_logs_outcome_rounds_calls_found_and_duration(capsys: pytest.CaptureFixture[str]) -> None:
    _, (line,), _ = logged(capsys, Brain([ask("search_web", "find_places"), ask("search_web"), answer()]))
    assert (line["tool"], line["outcome"], line["calls"], line["found"].lower()) == ("look_up", "ok", "3", "true")
    assert int(line["rounds"]) in (2, 3) and line["duration_ms"].isdigit()


def test_a_look_up_that_found_nothing_logs_found_false_and_outcome_ok(capsys: pytest.CaptureFixture[str]) -> None:
    _, (line,), _ = logged(capsys, Brain([answer("nothing", False, [])]))
    assert (line["outcome"], line["calls"], line["found"].lower()) == ("ok", "0", "false")
    assert int(line["rounds"]) in (0, 1)


def test_the_other_outcomes_are_logged(capsys: pytest.CaptureFixture[str]) -> None:
    _, (line,), _ = logged(capsys, Brain(), arguments={"question": " "})
    assert (line["tool"], line["outcome"]) == ("look_up", "error")
    _, (line,), _ = logged(capsys, Brain([InferenceUnavailable("x")]))
    assert (line["tool"], line["outcome"]) == ("look_up", "unavailable")
    _, (line,), _ = logged(capsys, Brain([ask("search_web"), InferenceRefused("x")]))
    assert (line["outcome"], line["calls"]) == ("unavailable", "1")
    _, (line,), _ = logged(capsys, Brain(), name="search_web", arguments={})
    assert line["outcome"] == "unknown_tool"


def test_the_question_the_answer_the_sources_and_the_results_reach_no_log_line(capsys: pytest.CaptureFixture[str]) -> None:
    question, said = f"hours of {MARK}q", f"{MARK}a"
    sources = Sources({"search_web": (f"{MARK}r", False)})
    script: list[LookedUp | ToolCalls | Exception] = [ask("search_web"), answer(said, True, [f"{MARK}s.example"])]
    brain = Brain(script)
    result, lines, out = logged(capsys, brain, question=question, sources=sources)
    assert len(lines) == 1, "control: the call was logged"
    assert said in result.content and f"{MARK}s.example" in result.content, "control: the marker is in the result"
    assert brain.seen[0].prompt.messages == (Message("person", question),), "control: the question reached the model"
    assert results_of(brain.seen[1].prompt).results[0].content == f"{MARK}r", "control: so did the result"
    assert MARK not in out and "hours of" not in out and "Open until" not in out
    _, _, out = logged(capsys, Brain([InferenceRefused(MARK)]), question=question)
    assert MARK not in out and "hours of" not in out



# look_up.json

SHIPPED = Path(look_up_config.__file__).parent / "look_up.json"
GOOD: dict[str, Any] = {"max_rounds": 3, "result_chars": 12500, "answer_chars": 500, "max_sources": 3,
                        "page_timeout_s": 6, "max_redirects": 3, "page_bytes": 1000000, "page_chars": 6000}


def serve(monkeypatch: pytest.MonkeyPatch, data: dict[str, Any]) -> None:
    """Whatever reads `look_up.json` through pathlib gets `data`; every other file reads as before."""
    text = json.dumps(data)
    real_text, real_bytes = Path.read_text, Path.read_bytes

    def read_text(self: Path, *a: Any, **k: Any) -> str:
        return text if self.name == "look_up.json" else real_text(self, *a, **k)

    def read_bytes(self: Path) -> bytes:
        return text.encode() if self.name == "look_up.json" else real_bytes(self)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def test_the_shipped_file_holds_the_contracts_values_and_loads() -> None:
    assert json.loads(SHIPPED.read_text()) == GOOD
    config = load()
    assert dataclasses.asdict(config) == GOOD
    assert isinstance(config, LookUpConfig) and dataclasses.is_dataclass(config)


def test_the_config_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(load(), "max_rounds", 9)


def test_a_good_file_served_through_the_patch_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {**GOOD, "max_rounds": 5})
    assert load().max_rounds == 5, "control: the patch is what load() reads"


@pytest.mark.parametrize("key", list(GOOD))
def test_a_missing_key_is_a_value_error(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    serve(monkeypatch, {k: v for k, v in GOOD.items() if k != key})
    with pytest.raises(ValueError):
        load()


def test_an_unknown_key_is_a_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {**GOOD, "max_round": 3})
    with pytest.raises(ValueError):
        load()


@pytest.mark.parametrize("bad", [0, -1])
@pytest.mark.parametrize("key", list(GOOD))
def test_a_number_that_is_not_positive_is_a_value_error(monkeypatch: pytest.MonkeyPatch, key: str, bad: int) -> None:
    serve(monkeypatch, {**GOOD, key: bad})
    with pytest.raises(ValueError):
        load()


# persona

SEARCH = "You can't look things up right now. Say so if asked."
HOUSE = facts.UNREACHABLE


def test_the_two_keys_are_house_and_search() -> None:
    assert facts.tools(None, True, ("search",)) == "# Tools\n\n" + SEARCH
    assert facts.tools(None, True, ("house",)) == "# Tools\n\n" + HOUSE
    assert facts.tools(None, True, ("house", "search")) == "# Tools\n\n" + HOUSE + " " + SEARCH


@pytest.mark.parametrize("key", ["web", "places"])
def test_the_old_source_keys_give_no_sentence(key: str) -> None:
    assert facts.tools(None, True, (key,)) is None
    assert facts.tools("zqINSTR", True, (key,)) == "# Tools\n\nzqINSTR"


def test_the_system_prompt_carries_the_search_sentence_and_not_the_old_ones() -> None:
    for text in (p.text for p in system("chat", replace(CONTEXT, tools_unreachable=("search",))).values()):
        assert SEARCH in text and "can't search the web" not in text and "look up places" not in text


# routes

def test_the_task_is_named_and_has_the_routes_the_contract_gives() -> None:
    assert "look_up" in get_args(Task) and "look_up" in routes.TASKS
    data: Any = json.loads((Path(routes.__file__).parent / "routes.json").read_text())
    assert data["tasks"]["look_up"] == [
        {"provider": "anthropic", "model": "claude-haiku-5-5", "timeout_s": 15,
         "params": {"max_tokens": 1024, "effort": "low"}},
        {"provider": "gemini", "model": "gemini-3.5-flash-lite", "timeout_s": 15,
         "params": {"max_completion_tokens": 1024}},
    ]


def test_both_models_have_a_price() -> None:
    prices: Any = json.loads((Path(routes.__file__).parent / "prices.json").read_text())
    assert "claude-haiku-5-5" in prices["anthropic"]["models"]
    assert "gemini-3.5-flash-lite" in prices["gemini"]["models"]
