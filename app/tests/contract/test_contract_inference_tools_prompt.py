"""`Prompt` with tools: every documented rejection (ValueError at construction) and the valid tool exchanges that must
pass, by example and by property."""

import pytest
from ashley.inference.model import Entry, Message, Prompt, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from hypothesis import given
from hypothesis import strategies as st
from inference_tools_support import LIGHTS, SYSTEM, WEATHER, call, exchanges, one_round, results_for, tool_prompt

ASK = Message("person", "turn it on")


def test_a_round_with_one_call_is_valid() -> None:
    assert one_round().messages[-1] == results_for((call(),))


def test_several_calls_in_one_round_are_valid() -> None:
    calls = (call("a"), call("b", "weather"), call("c"))
    assert len(one_round(calls).messages) == 3


def test_several_rounds_are_valid_and_ids_may_repeat_across_rounds() -> None:
    first, second = (call("c1"),), (call("c1", "weather"),)
    prompt = tool_prompt(ASK, ToolCalls(first), results_for(first), Message("ashley", "ok"), Message("person", "again"),
                         ToolCalls(second), results_for(second))
    assert len(prompt.messages) == 7


def test_a_person_message_may_follow_results() -> None:
    calls = (call(),)
    tool_prompt(ASK, ToolCalls(calls), results_for(calls), Message("ashley", "done"), Message("person", "thanks"))


def test_results_carrying_errors_are_valid() -> None:
    calls = (call(),)
    tool_prompt(ASK, ToolCalls(calls), results_for(calls, "boom", True))


def test_tool_choice_none_is_valid_with_tools_and_history() -> None:
    assert one_round(tool_choice="none").tool_choice == "none"


def test_tool_choice_defaults_to_auto_and_tools_to_none() -> None:
    plain = Prompt(dict(SYSTEM), (ASK,))
    assert plain.tools == () and plain.tool_choice == "auto"


def test_tools_are_allowed_with_no_tool_history() -> None:
    assert tool_prompt(ASK).tools == (LIGHTS, WEATHER)


@given(exchanges())
def test_every_generated_valid_exchange_is_accepted(drawn: tuple[tuple[ToolSpec, ...], tuple[Entry, ...]]) -> None:
    tools, entries = drawn
    prompt = Prompt(dict(SYSTEM), entries, tools)
    assert prompt.messages == entries and prompt.tools == tools


@given(exchanges(), st.data())
def test_dropping_the_results_of_any_round_is_rejected(drawn: tuple[tuple[ToolSpec, ...], tuple[Entry, ...]],
                                                       data: st.DataObject) -> None:
    tools, entries = drawn
    results_at = [i for i, e in enumerate(entries) if isinstance(e, ToolResults)]
    if not results_at:
        return
    cut = data.draw(st.sampled_from(results_at))
    broken = tuple(e for i, e in enumerate(entries) if i != cut)
    with pytest.raises(ValueError):
        Prompt(dict(SYSTEM), broken, tools)


@given(exchanges(), st.data())
def test_reordering_the_results_of_a_multi_call_round_is_rejected(
        drawn: tuple[tuple[ToolSpec, ...], tuple[Entry, ...]], data: st.DataObject) -> None:
    tools, entries = drawn
    multi = [i for i, e in enumerate(entries) if isinstance(e, ToolResults) and len(e.results) > 1]
    if not multi:
        return
    at = data.draw(st.sampled_from(multi))
    rs = entries[at]
    assert isinstance(rs, ToolResults)
    swapped = ToolResults((rs.results[1], rs.results[0], *rs.results[2:]))
    broken = (*entries[:at], swapped, *entries[at + 1:])
    with pytest.raises(ValueError):
        Prompt(dict(SYSTEM), broken, tools)


@pytest.mark.parametrize("system", [{}, {"other": "x"}, {"default": ""}, {"default": "  \n"},
                                    {"default": "ok", "tuned": " "}])
def test_a_system_without_a_default_or_with_an_empty_prompt_is_rejected(system: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Prompt({k: SystemPrompt(v) for k, v in system.items()}, (ASK,))


def test_no_messages_is_rejected() -> None:
    with pytest.raises(ValueError):
        Prompt(dict(SYSTEM), (), (LIGHTS,))


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_an_empty_or_blank_message_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        Prompt(dict(SYSTEM), (Message("person", text),))
    with pytest.raises(ValueError):
        Prompt(dict(SYSTEM), (Message("person", "hi"), Message("ashley", text), Message("person", "yo")))


def test_a_prompt_ending_on_ashley_is_rejected() -> None:
    with pytest.raises(ValueError):
        Prompt(dict(SYSTEM), (ASK, Message("ashley", "hi")))


def test_a_prompt_ending_on_tool_calls_is_rejected() -> None:
    with pytest.raises(ValueError):
        tool_prompt(ASK, _calls(call()))


def test_an_empty_tool_calls_is_rejected() -> None:
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(()), ToolResults(()))


def test_repeated_ids_in_one_tool_calls_are_rejected() -> None:
    twice = (call("x"), call("x", "weather"))
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(twice), results_for(twice))


def test_calls_not_followed_by_results_are_rejected() -> None:
    with pytest.raises(ValueError):
        tool_prompt(ASK, _calls(call()), Message("person", "hello?"))
    with pytest.raises(ValueError):
        tool_prompt(ASK, _calls(call()), _calls(call("c2")), results_for((call("c2"),)))


def test_results_after_anything_but_calls_are_rejected() -> None:
    with pytest.raises(ValueError):
        tool_prompt(ASK, results_for((call(),)))
    with pytest.raises(ValueError):
        tool_prompt(ASK, Message("ashley", "hm"), Message("person", "x"), results_for((call(),)))


def test_two_results_entries_in_a_row_are_rejected() -> None:
    calls = (call(),)
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(calls), results_for(calls), results_for(calls))


def test_results_missing_a_call_are_rejected() -> None:
    calls = (call("a"), call("b"))
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(calls), ToolResults((ToolResult("a", "x"),)))


def test_results_with_an_extra_or_unknown_id_are_rejected() -> None:
    calls = (call("a"),)
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(calls), ToolResults((ToolResult("a", "x"), ToolResult("b", "y"))))
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(calls), ToolResults((ToolResult("zzz", "x"),)))


def test_results_in_another_order_are_rejected() -> None:
    calls = (call("a"), call("b"))
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(calls), ToolResults((ToolResult("b", "x"), ToolResult("a", "y"))))


def test_results_answering_an_earlier_round_are_rejected() -> None:
    first, second = (call("a"),), (call("b"),)
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(first), results_for(first), Message("ashley", "k"), Message("person", "x"),
                    ToolCalls(second), results_for(first))


def test_tool_calls_with_no_tools_offered_are_rejected() -> None:
    calls = (call(),)
    with pytest.raises(ValueError):
        tool_prompt(ASK, ToolCalls(calls), results_for(calls), tools=())


def test_two_tools_sharing_a_name_are_rejected() -> None:
    with pytest.raises(ValueError):
        tool_prompt(ASK, tools=(LIGHTS, ToolSpec("lights_on", "again", {"type": "object"})))


def test_the_variant_lookup_falls_back_to_the_default() -> None:
    prompt = Prompt({"default": SystemPrompt("d"), "tuned": SystemPrompt("t")}, (ASK,))
    assert (prompt.system_for("tuned"), prompt.system_for("missing")) == (SystemPrompt("t"), SystemPrompt("d"))


def _calls(*calls: ToolCall) -> ToolCalls:
    return ToolCalls(calls)
