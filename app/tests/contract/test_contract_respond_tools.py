"""`respond`, step 5: each `ToolCalls` run through `Tools.call` one at a time in the order asked and sent back as
`ToolResults`; a result past the kind's `max_tool_result_chars` cut to it, with the cut said in what she reads; after `max_tool_rounds` rounds one more step
under tool choice `none`; a reply under `auto` that is not the answer asked again under `auto` with the act note; tool calls and
results never stored as turns. Limits are read from `turns.json`."""

import pytest
from ashley.channels import unsaid
from ashley.channels.respond import respond
from ashley.conversations.model import Kind
from ashley.inference.model import Message, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from conversations_support import KINDS
from inference_support import settle
from turns_support import LIMITS, World, asks, inbound, world as world


def test_the_shipped_limits_cover_every_kind() -> None:
    assert set(LIMITS) == set(KINDS)
    for limits in LIMITS.values():
        assert limits["max_tool_rounds"] >= 1 and limits["max_tool_result_chars"] >= 1


def test_each_call_runs_in_order_and_its_result_goes_back_after_it(world: World) -> None:
    calls = asks("weather", "lights", "weather")
    world.inference.script = [calls]
    out = settle(respond(inbound(text="lights and weather", speaker_id=None, shared=False)))
    assert world.tools.called == list(calls.calls)
    first, second = world.inference.asked
    assert second.prompt.messages[:len(first.prompt.messages)] == first.prompt.messages
    assert second.prompt.messages[len(first.prompt.messages):] == (calls, ToolResults(tuple(
        ToolResult(c.id, f'{{"ok": true, "call": "{c.id}"}}') for c in calls.calls)))
    assert second.prompt.tool_choice == "auto" and second.prompt.tools == first.prompt.tools
    assert [a for a, _, _ in world.conversations.turns_of(out.conversation_id)] == ["person", "ashley"]


def test_rounds_accumulate_in_order(world: World) -> None:
    one, two = asks("lights", round_=1), asks("weather", "lights", round_=2)
    world.inference.script = [one, two]
    settle(respond(inbound(kind="chat")))
    assert len(world.inference.asked) == 3
    tail = world.inference.asked[2].prompt.messages[-4:]
    assert [type(e) for e in tail] == [ToolCalls, ToolResults, ToolCalls, ToolResults]
    assert tail[0] == one and tail[2] == two
    assert world.tools.called == [*one.calls, *two.calls]


def test_an_error_result_goes_back_marked_as_an_error(world: World) -> None:
    world.tools.results["lights"] = ToolResult("ignored", "no such light", is_error=True)
    world.inference.script = [asks("lights")]
    settle(respond(inbound()))
    results = world.inference.asked[1].prompt.messages[-1]
    assert results == ToolResults((ToolResult("r0c0", "no such light", is_error=True),))


@pytest.mark.parametrize("kind", KINDS)
def test_a_result_past_the_kinds_limit_is_cut_to_it_and_says_so(world: World, kind: Kind) -> None:
    limit = LIMITS[kind]["max_tool_result_chars"]
    long = "".join(chr(ord("a") + i % 26) for i in range(limit + 777))
    world.tools.results["lights"] = ToolResult("x", long)
    world.tools.results["weather"] = ToolResult("x", long[:limit])
    world.inference.script = [asks("lights", "weather")]
    settle(respond(inbound(kind=kind)))
    results = world.inference.asked[1].prompt.messages[-1]
    assert isinstance(results, ToolResults)
    cut, exact = results.results
    assert len(cut.content) <= limit and cut.content.startswith("[cut:")
    assert f"of {len(long)} characters" in cut.content
    shown = int(cut.content.split("first ")[1].split(" of")[0])
    assert shown > 0 and cut.content.endswith(long[:shown]), "the marker says exactly how much of the head follows"
    assert exact.content == long[:limit], "a result exactly at the limit is left whole"


@pytest.mark.parametrize("kind", KINDS)
def test_after_the_kinds_rounds_one_more_step_must_answer(world: World, kind: Kind) -> None:
    rounds = LIMITS[kind]["max_tool_rounds"]
    world.inference.script = [asks("lights", "weather", round_=r) for r in range(rounds)]
    world.inference.then = asks("lights", "weather")
    out = settle(respond(inbound(kind=kind, medium="text")))
    choices = [a.prompt.tool_choice for a in world.inference.asked]
    assert choices == ["auto"] * rounds + ["none"]
    assert len(world.tools.called) == 2 * rounds
    last = world.inference.asked[-1].prompt
    assert sum(isinstance(e, ToolResults) for e in last.messages) == rounds
    assert out.body == "done"


def test_a_reply_before_the_limit_ends_the_loop_with_no_none_step(world: World) -> None:
    world.inference.script = [asks("lights"), asks("weather")]
    settle(respond(inbound(kind="brainstorm")))
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto", "auto", "auto"]


def test_tool_calls_and_results_are_never_stored(world: World) -> None:
    world.inference.script = [asks("lights"), asks("weather")]
    out = settle(respond(inbound(text="go")))
    assert world.conversations.turns_of(out.conversation_id) == [("person", None, "go"),
                                                                 ("ashley", None, "The lights are on.")]


def test_the_conversation_is_sent_once_not_again_each_round(world: World) -> None:
    world.inference.script = [asks("lights"), asks("weather")]
    settle(respond(inbound(text="go")))
    for asked in world.inference.asked:
        assert [e for e in asked.prompt.messages if isinstance(e, Message)] == [Message("person", "go")]


PROMISE = Reply(answers=False, spoken="Let me check.", text="Let me check.")


def test_a_reply_that_is_not_the_answer_is_asked_again_under_auto(world: World) -> None:
    weather = asks("weather")
    world.inference.script = [PROMISE, weather]
    out = settle(respond(inbound(text="weather?", medium="text")))
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto", "auto", "auto"]
    assert world.inference.asked[1].prompt.messages == (*world.inference.asked[0].prompt.messages, unsaid.ACT)
    assert world.tools.called == list(weather.calls)
    assert world.conversations.turns_of(out.conversation_id)[-1] == ("ashley", None, "**Lights on.**")


def test_a_second_promise_after_the_tools_is_asked_again_too(world: World) -> None:
    world.inference.script = [PROMISE, asks("weather"), PROMISE, asks("lights", round_=1)]
    settle(respond(inbound()))
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto", "auto", "auto", "auto", "auto"]


def test_a_reply_that_is_the_answer_is_not_asked_again(world: World) -> None:
    settle(respond(inbound()))
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto"]


def test_with_no_tools_offered_a_promise_is_her_reply(world: World) -> None:
    world.tools.on_offer = None
    world.inference.script = [PROMISE]
    out = settle(respond(inbound(medium="text")))
    assert len(world.inference.asked) == 1
    assert world.conversations.turns_of(out.conversation_id)[-1] == ("ashley", None, "Let me check.")


def test_under_tool_choice_none_a_promise_is_asked_once_to_say_where_things_stand(world: World) -> None:
    rounds = LIMITS["command"]["max_tool_rounds"]
    stood = Reply(spoken="It is half done.", text="It is half done.")
    world.inference.script = [*(asks("lights", round_=r) for r in range(rounds)), PROMISE, stood]
    out = settle(respond(inbound()))
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto"] * rounds + ["none", "none"]
    assert world.conversations.turns_of(out.conversation_id)[-1] == ("ashley", None, "It is half done.")
