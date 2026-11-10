"""`RoutedInference.step` with scripted providers: a reply or the tools asked for, what each provider receives, route
order and restarting at the first route, skips, resting, refusal, calls the router must reject, and `generate`
refusing a prompt that carries tools."""

import pytest
from ashley.inference.inference import InferenceRefused, InferenceRejected, InferenceUnavailable
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.inference.router import RoutedInference
from inference_support import ANY_TASK, COOLDOWN_S, FAILURES, Clock, FakeLedger, outcomes, route, router, settle, table
from ashley.inference.provider import Failure
from inference_tools_support import LIGHTS, TOOLS, Turn, broke, call, declined, one_round, provider, say, tool_prompt, want
from pydantic import BaseModel

ASK = Message("person", "turn it on")


def step(inference: RoutedInference, prompt: Prompt | None = None, task: Task = "chat") -> Reply | ToolCalls:
    return settle(inference.step(task, prompt or tool_prompt(ASK), Reply))


def spoken(answer: Reply | ToolCalls) -> str:
    assert isinstance(answer, Reply), "expected a reply"
    return answer.text


def test_a_route_that_answers_gives_the_reply() -> None:
    p = provider("a", say("hi"))
    assert step(router(table([route("a")]), [p])) == Reply(spoken="hi", text="hi")


def test_a_route_that_asks_for_tools_gives_those_calls_in_order() -> None:
    asked = (call("x1", "weather", q="now"), call("x2", "lights_on", q="hall"), call("x3", "weather", q="later"))
    p = provider("a", want(*asked))
    got = step(router(table([route("a")]), [p]))
    assert got == ToolCalls(asked)


def test_the_answer_is_shaped_as_the_asked_for_output() -> None:
    class Verdict(BaseModel):
        yes: bool

    p = provider("a", Turn(data={"yes": True}))
    got = settle(router(table([route("a")]), [p]).step("chat", tool_prompt(ASK), Verdict))
    assert got == Verdict(yes=True)
    assert p.got[0].output is Verdict


def test_the_provider_receives_the_tools_choice_history_system_and_route_settings() -> None:
    p = provider("a", say())
    prompt = one_round(tool_choice="none", system={"default": SystemPrompt("d"), "tuned": SystemPrompt("t")})
    inference = router(table([route("a", "m7", 4.5, "tuned", {"k": 1})]), [p])
    step(inference, prompt)
    got = p.got[0]
    assert (got.model, got.system, got.timeout_s, dict(got.params)) == ("m7", SystemPrompt("t"), 4.5, {"k": 1})
    assert got.messages == prompt.messages
    assert (got.tools, got.tool_choice) == (TOOLS, "none")


def test_a_prompt_with_no_tools_is_allowed_and_sends_none() -> None:
    p = provider("a", say("plain"))
    got = step(router(table([route("a")]), [p]), tool_prompt(ASK, tools=()))
    assert got == Reply(spoken="plain", text="plain")
    assert p.got[0].tools == ()


def test_the_next_step_starts_again_at_the_first_route() -> None:
    a, b = provider("a", want(call()), say("final")), provider("b", say("from b"))
    inference = router(table([route("a"), route("b")]), [a, b])
    assert isinstance(step(inference), ToolCalls)
    assert step(inference, one_round()) == Reply(spoken="final", text="final")
    assert (len(a.got), len(b.got)) == (2, 0)


def test_a_loop_may_be_carried_by_more_than_one_provider() -> None:
    a = provider("a", want(call("c1")), broke("unavailable"))
    b = provider("b", say("closing"))
    inference = router(table([route("a"), route("b")]), [a, b])
    assert isinstance(step(inference), ToolCalls)
    assert spoken(step(inference, one_round((call("c1"),)))) == "closing"
    assert len(b.got) == 1 and b.got[0].messages == one_round((call("c1"),)).messages


@pytest.mark.parametrize("failure", FAILURES)
def test_a_failed_call_moves_on_to_the_next_route_which_may_ask_for_tools(failure: Failure) -> None:
    a, b = provider("a", broke(failure)), provider("b", want(call("z")))
    ledger = FakeLedger()
    got = step(router(table([route("a"), route("b")]), [a, b], ledger))
    assert got == ToolCalls((call("z"),))
    assert outcomes(ledger) == [("a", "m1", failure), ("b", "m1", "ok")]


def test_routes_are_per_task() -> None:
    a, b = provider("a", say("chat")), provider("b", say("command"))
    inference = router(table([route("a")], overrides={"command": [route("b")]}), [a, b])
    assert step(inference, task="command") == Reply(spoken="command", text="command")
    assert a.got == []


def test_an_unwired_route_is_skipped() -> None:
    b = provider("b", want(call()))
    ledger = FakeLedger()
    assert isinstance(step(router(table([route("ghost"), route("b")]), [b], ledger)), ToolCalls)
    assert outcomes(ledger) == [("b", "m1", "ok")]


def test_a_provider_resting_after_unavailable_is_skipped_until_the_cooldown_passes() -> None:
    clock = Clock()
    a, b = provider("a", broke("unavailable"), want(call())), provider("b", say("fallback"))
    inference = router(table([route("a"), route("b")]), [a, b], clock=clock)
    assert spoken(step(inference)) == "fallback"
    assert spoken(step(inference)) == "fallback"
    assert len(a.got) == 1, "resting: not called again"
    clock.advance(COOLDOWN_S + 1)
    assert isinstance(step(inference), ToolCalls)
    assert len(a.got) == 2


def test_resting_set_by_a_generate_call_also_skips_in_step() -> None:
    clock = Clock()
    a, b = provider("a", broke("unavailable")), provider("b", say("b"))
    inference = router(table([route("a"), route("b")]), [a, b], clock=clock)
    settle(inference.generate("chat", tool_prompt(ASK, tools=()), Reply))
    step(inference)
    assert len(a.got) == 1


def test_a_failure_other_than_unavailable_does_not_rest_the_provider() -> None:
    a = provider("a", broke("invalid_output"), want(call()))
    inference = router(table([route("a")]), [a])
    with pytest.raises(InferenceUnavailable):
        step(inference)
    assert isinstance(step(inference), ToolCalls)


def test_a_refusal_is_final_and_no_other_route_is_asked() -> None:
    a, b = provider("a", declined()), provider("b")
    ledger = FakeLedger()
    with pytest.raises(InferenceRefused):
        step(router(table([route("a"), route("b")]), [a, b], ledger))
    assert b.got == [] and outcomes(ledger) == [("a", "m1", "refused")]


def test_no_route_answering_raises_unavailable() -> None:
    a = provider("a", broke("error"))
    with pytest.raises(InferenceUnavailable):
        step(router(table([route("a"), route("ghost")]), [a]))


def test_every_route_rejecting_the_request_raises_rejected_and_stays_a_kind_of_unavailable() -> None:
    a, b = provider("a", broke("error")), provider("b", broke("error"))
    with pytest.raises(InferenceRejected) as caught:
        step(router(table([route("a"), route("b")]), [a, b]))
    assert isinstance(caught.value, InferenceUnavailable)


@pytest.mark.parametrize("other", ["unavailable", "invalid_output"])
def test_one_route_failing_another_way_keeps_the_failure_plain_unavailable(other: Failure) -> None:
    a, b = provider("a", broke("error")), provider("b", broke(other))
    with pytest.raises(InferenceUnavailable) as caught:
        step(router(table([route("a"), route("b")]), [a, b]))
    assert not isinstance(caught.value, InferenceRejected)


def test_no_route_called_is_plain_unavailable_not_rejected() -> None:
    with pytest.raises(InferenceUnavailable) as caught:
        step(router(table([route("ghost")]), []))
    assert not isinstance(caught.value, InferenceRejected)


def test_an_unknown_task_raises_value_error_before_any_call() -> None:
    a, ledger = provider("a"), FakeLedger()
    with pytest.raises(ValueError):
        settle(router(table([route("a")]), [a], ledger).step(ANY_TASK, tool_prompt(ASK), Reply))
    assert a.got == [] and ledger.attempts == 0


# --- calls the router must reject ---------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    pytest.param((call("c1", "no_such_tool"),), id="unknown"),
    pytest.param((call("c1", "weather"), call("c2", "ghost_tool")), id="one-unknown-among-known"),
    pytest.param((call("c1", "weather"), call("c1", "lights_on")), id="repeated-id"),
    pytest.param((call("c1", "weather"), call("c1", "weather")), id="same-call-twice"),
])
def test_calls_naming_an_unknown_tool_or_repeating_an_id_fail_invalid_output_and_the_next_route_is_tried(
        bad: tuple[ToolCall, ...]) -> None:
    a, b = provider("a", want(*bad)), provider("b", say("from b"))
    ledger = FakeLedger()
    got = step(router(table([route("a"), route("b")]), [a, b], ledger))
    assert got == Reply(spoken="from b", text="from b")
    assert outcomes(ledger) == [("a", "m1", "invalid_output"), ("b", "m1", "ok")]


def test_invalid_calls_from_every_route_end_in_unavailable() -> None:
    a, b = provider("a", want(call("c1", "ghost"))), provider("b", want(call("q"), call("q")))
    ledger = FakeLedger()
    with pytest.raises(InferenceUnavailable):
        step(router(table([route("a"), route("b")]), [a, b], ledger))
    assert outcomes(ledger) == [("a", "m1", "invalid_output"), ("b", "m1", "invalid_output")]


def test_invalid_output_does_not_rest_the_provider() -> None:
    a = provider("a", want(call("c1", "ghost")), want(call()))
    inference = router(table([route("a")]), [a])
    with pytest.raises(InferenceUnavailable):
        step(inference)
    assert isinstance(step(inference), ToolCalls)


def test_tool_calls_for_a_prompt_with_no_tools_fail_invalid_output() -> None:
    a, b = provider("a", want(call("c1", "weather"))), provider("b", say("plain"))
    ledger = FakeLedger()
    got = step(router(table([route("a"), route("b")]), [a, b], ledger), tool_prompt(ASK, tools=()))
    assert got == Reply(spoken="plain", text="plain")
    assert outcomes(ledger)[0] == ("a", "m1", "invalid_output")


def test_a_tool_known_only_to_another_prompt_is_unknown_here() -> None:
    a, b = provider("a", want(call("c1", "weather"))), provider("b", say("x"))
    ledger = FakeLedger()
    step(router(table([route("a"), route("b")]), [a, b], ledger), tool_prompt(ASK, tools=(LIGHTS,)))
    assert outcomes(ledger)[0][2] == "invalid_output"


def test_under_tool_choice_none_the_answer_is_always_a_reply() -> None:
    a, b = provider("a", want(call())), provider("b", say("spoken"))
    ledger = FakeLedger()
    got = step(router(table([route("a"), route("b")]), [a, b], ledger), one_round(tool_choice="none"))
    assert got == Reply(spoken="spoken", text="spoken")
    assert outcomes(ledger) == [("a", "m1", "invalid_output"), ("b", "m1", "ok")]


def test_under_tool_choice_auto_tool_calls_answer_the_step() -> None:
    a, ledger = provider("a", want(call())), FakeLedger()
    got = step(router(table([route("a")]), [a], ledger), one_round(tool_choice="auto"))
    assert got == ToolCalls((call(),))
    assert outcomes(ledger) == [("a", "m1", "ok")]


# --- generate refuses tools ---------------------------------------------------------------------------------------


def test_generate_raises_value_error_for_a_prompt_with_tools_before_any_call() -> None:
    a, ledger = provider("a"), FakeLedger()
    inference = router(table([route("a")]), [a], ledger)
    with pytest.raises(ValueError):
        settle(inference.generate("chat", tool_prompt(ASK), Reply))
    with pytest.raises(ValueError):
        settle(inference.generate("chat", one_round(), Reply))
    assert a.got == [] and ledger.attempts == 0


def test_generate_refuses_tools_even_when_no_route_is_wired() -> None:
    inference = router(table([route("ghost")]), [])
    with pytest.raises(ValueError):
        settle(inference.generate("chat", tool_prompt(ASK), Reply))


def test_generate_still_answers_a_prompt_without_tools_through_the_new_provider_signature() -> None:
    a = provider("a", say("plain"))
    got = settle(router(table([route("a")]), [a]).generate("chat", tool_prompt(ASK, tools=()), Reply))
    assert got == Reply(spoken="plain", text="plain")
    assert (a.got[0].tools, a.got[0].tool_choice) == ((), "auto")

