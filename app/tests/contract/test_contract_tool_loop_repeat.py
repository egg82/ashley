"""`tool_loop.answer`: a read with the name and arguments of one already made in the same reply is not run again; its
result says she has the earlier one. Calls differing in name or arguments run as usual. A change that ran forgets every
read made before it, so a read after it runs again; a refused change forgets nothing; a repeated change is never
deduped."""

import logging

import pytest

from ashley.channels.limits import Limits
from ashley.channels.tool_loop import answer
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from inference_support import settle
from turns_support import OTHER_SPEC, SPEC, World, world as world

SET = ToolSpec("lights_set", "Turn a light on or off", {"type": "object", "properties": {}}, reads=False)
TOOLS: tuple[ToolSpec, ...] = (SPEC, OTHER_SPEC, SET)
LIMITS = Limits(max_tool_rounds=4, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0)
FINAL = Reply(spoken="Done.", text="Done.")


def again(round_: int) -> ToolCalls:
    return ToolCalls((ToolCall(f"r{round_}c0", "lights", {"n": 0}),))


def read(id_: str) -> ToolCall:
    return ToolCall(id_, "lights", {"n": 0})


def change(id_: str) -> ToolCall:
    return ToolCall(id_, "lights_set", {"on": True})


def ids(world: World) -> list[str]:
    return [c.id for c in world.tools.called]


def run(world: World) -> list[ToolResults]:
    settle(answer("chat", {"default": SystemPrompt("x")}, (Message("person", "hi"),), TOOLS, LIMITS, conversation_id=7))
    return [a for a in world.inference.asked[-1].prompt.messages if isinstance(a, ToolResults)]


def test_a_repeat_in_a_later_round_is_not_run_and_points_at_the_earlier_call(world: World) -> None:
    world.inference.script = [again(0), again(1), FINAL]
    results = run(world)
    assert [c.id for c in world.tools.called] == ["r0c0"]
    assert "r0c0" in results[1].results[0].content
    assert results[1].results[0].call_id == "r1c0"


def test_a_repeat_within_one_round_is_not_run(world: World) -> None:
    both = (ToolCall("a", "lights", {"x": 1, "y": 2}), ToolCall("b", "lights", {"y": 2, "x": 1}))
    world.inference.script = [ToolCalls(both), FINAL]
    results = run(world)
    assert [c.id for c in world.tools.called] == ["a"]
    assert len(results[0].results) == 2 and "a" in results[0].results[1].content


def test_a_different_name_or_arguments_still_runs(world: World) -> None:
    world.inference.script = [ToolCalls((ToolCall("a", "lights", {"x": 1}), ToolCall("b", "lights", {"x": 2}),
                                         ToolCall("c", "weather", {"x": 1}))), FINAL]
    run(world)
    assert [c.id for c in world.tools.called] == ["a", "b", "c"]


def test_a_repeat_of_a_call_that_errored_is_not_run(world: World) -> None:
    world.tools.results["lights"] = ToolResult("", "boom", is_error=True)
    world.inference.script = [again(0), again(1), FINAL]
    run(world)
    assert len(world.tools.called) == 1


def test_a_repeat_is_logged_with_the_conversation_and_no_arguments(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ashley.tools")
    world.inference.script = [ToolCalls((ToolCall("a", "lights", {"secret": "hunter2"}),)),
                              ToolCalls((ToolCall("b", "lights", {"secret": "hunter2"}),)), FINAL]
    run(world)
    found = [r for r in caplog.records if r.getMessage() == "tools.repeat"]
    assert [getattr(r, "fields") for r in found] == [{"conversation": 7, "repeats": 1, "tools": "lights"}]


def test_a_read_after_a_change_that_ran_runs_again(world: World) -> None:
    world.inference.script = [ToolCalls((read("r1"),)), ToolCalls((change("c"),)), ToolCalls((read("r2"),)), FINAL]
    run(world)
    assert ids(world) == ["r1", "c", "r2"]


def test_a_read_after_a_change_in_the_same_round_runs_again(world: World) -> None:
    world.inference.script = [ToolCalls((read("r1"), change("c"), read("r2"))), FINAL]
    run(world)
    assert ids(world) == ["r1", "c", "r2"]


def test_a_change_repeated_is_run_both_times(world: World) -> None:
    world.inference.script = [ToolCalls((change("c1"),)), ToolCalls((change("c2"),)), FINAL]
    run(world)
    assert ids(world) == ["c1", "c2"]
