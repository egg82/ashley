"""`Inference.prime` on `RoutedInference`: the route a `step` of the task would try first for the household (its choice
before the deployment's) is asked to read the prompt's prefix into its prompt cache, with the prompt's tools, the route's
system prompt variant and the output schema, and no messages. An answered or failed prime is one spend row and one
`inference.call` with `primed` true; a failed one rests nobody; a provider with no prompt cache is sent and billed
nothing and the answer is False; nothing escapes but ValueError for an unknown task or tools on a toolless task."""

import logging
from collections.abc import Iterable

import pytest
from ashley.inference import routes
from ashley.inference.inference import Inference
from ashley.inference.layered_routes import LayeredRoutes
from ashley.inference.model import Message, Prompt, SystemPrompt, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.route_choices import Choice
from ashley.inference.router import RoutedInference
from household_routes_support import Choices, data, events
from inference_support import (ANY_TASK, PRICES, USAGE, USAGE_COST, Clock, FakeLedger, FakeProvider, Step, fail, ok,
                               prompt, settle)

TOOLS = (ToolSpec("lights_on", "which lights are on", {"type": "object"}, True),
         ToolSpec("switch", "turn something on or off", {"type": "object"}))
PRIMED = Step(usage=USAGE)
CHOSE_BETA = Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1})


def routed(providers: Iterable[FakeProvider], choices: Choices = CHOSE_BETA) -> tuple[RoutedInference, FakeLedger]:
    wired = list(providers)
    names = frozenset(p.name for p in wired)
    layered = LayeredRoutes(data(), {p.name: p for p in wired}, lambda: names, choices, routes.without_fallback,
                            Clock(), 30.0)
    ledger = FakeLedger()
    return RoutedInference(layered.deployment(), wired, ledger, PRICES, Clock(), households=layered), ledger


def with_tools(*texts: str) -> Prompt:
    base = prompt(*texts, system={"default": "be Ashley"})
    return Prompt(base.system, base.messages, TOOLS)


def test_the_households_first_choice_is_primed_and_the_deployments_route_is_not() -> None:
    alpha, beta = FakeProvider("alpha", prime_script=[PRIMED]), FakeProvider("beta", prime_script=[PRIMED])
    router, _ = routed([alpha, beta])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)) is True
    assert (len(alpha.primed), len(beta.primed)) == (0, 1)
    assert beta.primed[0].model == "m1" and not alpha.asked and not beta.asked


def test_a_household_with_no_choice_primes_the_deployments_first_route() -> None:
    alpha, beta = FakeProvider("alpha", prime_script=[PRIMED]), FakeProvider("beta", prime_script=[PRIMED])
    router, _ = routed([alpha, beta])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=2)) is True
    assert (len(alpha.primed), len(beta.primed)) == (1, 0)


def test_the_prefix_primed_is_the_prompts_tools_system_and_the_output_with_the_routes_timeout_and_params() -> None:
    beta = FakeProvider("beta", prime_script=[PRIMED])
    router, _ = routed([beta])
    given = Prompt({"default": SystemPrompt("stable text", "moment text")}, (Message("person", "zqMESSAGE"),), TOOLS)
    settle(router.prime("chat", given, Reply, household_id=1))
    seen = beta.primed[0]
    assert (seen.tools, seen.output, seen.system) == (TOOLS, Reply, given.system["default"])
    assert (seen.model, seen.timeout_s) == ("m1", 10.0)


def test_the_variant_the_route_names_is_the_system_primed() -> None:
    names = frozenset({"alpha"})
    tuned = data()
    tuned["tasks"]["chat"] = {"household": True, "routes": [{"provider": "alpha", "model": "m1", "timeout_s": 10,
                                                              "variant": "terse", "params": {}}]}
    alpha = FakeProvider("alpha", prime_script=[PRIMED])
    layered = LayeredRoutes(tuned, {"alpha": alpha}, lambda: names, Choices(), routes.without_fallback, Clock(), 30.0)
    router = RoutedInference(layered.deployment(), [alpha], FakeLedger(), PRICES, Clock(), households=layered)
    given = Prompt({"default": SystemPrompt("plain"), "terse": SystemPrompt("short")}, (Message("person", "hi"),), TOOLS)
    settle(router.prime("chat", given, Reply, household_id=2))
    assert alpha.primed[0].system == SystemPrompt("short")


def test_an_answered_prime_is_one_spend_row_at_the_models_price_and_one_primed_call_event(
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    router, ledger = routed([FakeProvider("beta", prime_script=[PRIMED])])
    settle(router.prime("chat", with_tools("hi"), Reply, household_id=1))
    assert [(r.task, r.provider, r.model, r.outcome, r.usage, r.cost_usd) for r in ledger.rows] == [
        ("chat", "beta", "m1", "ok", USAGE, USAGE_COST)]
    calls = events(caplog, "inference.call")
    assert len(calls) == 1 and calls[0]["primed"] is True and calls[0]["outcome"] == "ok"


def test_a_failed_prime_is_recorded_as_its_failure_with_primed_true_and_answers_false(
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    router, ledger = routed([FakeProvider("beta", prime_script=[fail("error", usage=USAGE)])])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)) is False
    assert [(r.provider, r.outcome, r.usage) for r in ledger.rows] == [("beta", "error", USAGE)]
    calls = events(caplog, "inference.call")
    assert len(calls) == 1 and calls[0]["primed"] is True and calls[0]["outcome"] == "error"


def test_an_ordinary_step_is_not_logged_as_primed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    router, _ = routed([FakeProvider("beta")])
    settle(router.step("chat", with_tools("hi"), Reply, conversation_id=None))
    assert not [c for c in events(caplog, "inference.call") if c.get("primed")]


def test_a_failed_prime_does_not_rest_the_provider_so_the_next_step_still_calls_it() -> None:
    beta = FakeProvider("beta", [ok()], prime_script=[fail("unavailable")])
    router, _ = routed([FakeProvider("alpha"), beta])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)) is False
    settle(router.step("chat", with_tools("hi"), Reply, conversation_id=10))
    assert len(beta.asked) == 1


def test_the_control_a_failed_step_does_rest_the_provider() -> None:
    names = frozenset({"alpha"})
    alpha = FakeProvider("alpha", [fail("unavailable"), ok()], prime_script=[fail("unavailable")])
    layered = LayeredRoutes(data(), {"alpha": alpha}, lambda: names, Choices(), routes.without_fallback, Clock(), 30.0)
    router = RoutedInference(layered.deployment(), [alpha], FakeLedger(), PRICES, Clock(), households=layered)
    with pytest.raises(Exception):
        settle(router.generate("brainstorm", prompt("hi"), Reply))
    with pytest.raises(Exception):
        settle(router.generate("brainstorm", prompt("hi"), Reply))
    assert len(alpha.asked) == 1, "the control: a failed call rested it, which a failed prime must not"


def test_a_provider_with_no_prompt_cache_is_sent_and_billed_nothing_and_answers_false(
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    beta = FakeProvider("beta", prime_script=[None])
    router, ledger = routed([beta])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)) is False
    assert len(beta.primed) == 1 and not beta.asked
    assert ledger.rows == [] and ledger.attempts == 0 and not events(caplog, "inference.call")


def test_a_provider_that_does_not_override_prime_primes_nothing() -> None:
    beta = FakeProvider("beta")
    router, ledger = routed([beta])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)) is False
    assert ledger.rows == [] and not beta.asked


def test_an_exception_escaping_the_provider_is_an_answer_of_false_not_a_raise() -> None:
    router, _ = routed([FakeProvider("beta", prime_script=[RuntimeError("boom")])])
    assert settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)) is False


def test_a_ledger_that_cannot_write_does_not_make_prime_raise() -> None:
    beta = FakeProvider("beta", prime_script=[PRIMED])
    router, ledger = routed([beta])
    ledger.fail_with = OSError("down")
    assert isinstance(settle(router.prime("chat", with_tools("hi"), Reply, household_id=1)), bool)


def test_a_route_whose_provider_is_not_wired_is_not_primed_and_nothing_is_billed() -> None:
    alpha = FakeProvider("alpha", prime_script=[PRIMED])
    router, ledger = routed([alpha])
    assert settle(router.prime("command", with_tools("hi"), Reply, household_id=1)) is False
    assert ledger.rows == [] and not alpha.primed


def test_an_unknown_task_raises_value_error_before_anything_is_sent() -> None:
    beta = FakeProvider("beta", prime_script=[PRIMED])
    router, ledger = routed([beta])
    with pytest.raises(ValueError):
        settle(router.prime(ANY_TASK, with_tools("hi"), Reply, household_id=1))
    assert not beta.primed and ledger.rows == []


def test_tools_for_a_toolless_task_raise_value_error_before_anything_is_sent_and_no_tools_are_allowed() -> None:
    names = frozenset({"alpha"})
    alpha = FakeProvider("alpha", prime_script=[PRIMED])
    layered = LayeredRoutes(data(), {"alpha": alpha}, lambda: names, Choices(), routes.without_fallback, Clock(), 30.0)
    router = RoutedInference(layered.deployment(), [alpha], FakeLedger(), PRICES, Clock(), households=layered)
    with pytest.raises(ValueError):
        settle(router.prime("memory_write", with_tools("hi"), Reply, household_id=1))
    assert not alpha.primed
    assert settle(router.prime("memory_write", prompt("hi"), Reply, household_id=1)) is True


def test_the_default_inference_primes_nothing() -> None:
    assert settle(Inference.null().prime("chat", with_tools("hi"), Reply, household_id=1)) is False
