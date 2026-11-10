"""`LayeredRoutes`: a household with no choices walks exactly the deployment's routes; a choice goes first with the
deployment's routes after it; what it may choose; what is dropped, kept while unwired, and how stale a pod may be."""

import logging
from copy import deepcopy
from typing import Any

import pytest
from ashley.inference import routes
from ashley.inference.layered_routes import LayeredRoutes
from ashley.inference.model import Route
from ashley.inference.route_choices import Choice
from contract.inference_support import Clock, settle
from household_routes_support import Choices, data, events, raw

ALPHA1, BETA1 = Route("alpha", "m1", 10.0), Route("beta", "m1", 10.0)
ALPHA2 = Route("alpha", "m2", 60.0, params={"depth": "deep"})
BETA_COMMAND = Route("beta", "m1", 5.0)


def layered(choices: Choices, wired: frozenset[str] = frozenset({"alpha", "beta"}),
            clock: Clock | None = None, source: dict[str, Any] | None = None) -> LayeredRoutes:
    return LayeredRoutes(source or data(), {}, lambda: wired, choices, routes.without_fallback, clock or Clock(), 30.0)


def plain(source: dict[str, Any]) -> dict[str, Any]:
    """`source` with every household entry written as the plain list it held before households could choose."""
    out = deepcopy(source)
    for task in routes.parse(source, {}).households:
        entry: dict[str, Any] = out["tasks"][task]
        del entry["household"]
        if set(entry) == {"routes"}:
            out["tasks"][task] = entry["routes"]
    return out


def test_the_shipped_household_flags_change_no_route_any_task_walks() -> None:
    shipped = routes.deployment()
    flagged, before = routes.parse(shipped, {}), routes.parse(plain(shipped), {})
    assert flagged.households == {"command", "chat", "brainstorm"}
    assert (flagged.by_task, flagged.waits_for_first, flagged.cooldown_s) == (
        before.by_task, before.waits_for_first, before.cooldown_s)


def test_a_household_with_no_choices_gets_exactly_the_routes_it_got_before() -> None:
    shipped = routes.deployment()
    before = routes.without_fallback(routes.parse(plain(shipped), {}))
    choices = Choices({2: {"chat": Choice("anthropic", "claude-opus-5-5")}}, {10: 1, 20: 2})
    got = layered(choices, frozenset({"anthropic", "gemini", "openai"}), source=shipped)
    for conversation in (None, 10, 99):
        walked = settle(got.for_call(conversation))
        assert walked.by_task == before.by_task and walked == got.deployment()
    assert settle(got.for_call(20)).by_task["chat"][0].model == "claude-opus-5-5"


def test_with_nothing_stored_no_conversation_is_looked_up() -> None:
    choices = Choices(homes={10: 1})
    got = layered(choices)
    assert settle(got.for_call(10)) == got.deployment()
    assert choices.lookups == 0


def test_a_choice_goes_first_and_the_deployments_routes_follow_without_it() -> None:
    got = layered(Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1}))
    walked = settle(got.for_call(10))
    assert walked.by_task["chat"] == (BETA1, ALPHA1)
    assert walked.by_task["command"] == got.deployment().by_task["command"]


def test_a_choice_already_in_the_list_moves_to_the_front_once() -> None:
    source = data()
    source["tasks"]["chat"]["routes"] = [raw("alpha", "m1"), raw("alpha", "m2", 60, depth="deep")]
    got = layered(Choices({1: {"chat": Choice("alpha", "m2")}}, {10: 1}), source=source)
    assert settle(got.for_call(10)).by_task["chat"] == (ALPHA2, ALPHA1)


def test_a_task_like_a_chosen_one_follows_it() -> None:
    got = layered(Choices({1: {"brainstorm": Choice("beta", "m1")}}, {10: 1}))
    walked = settle(got.for_call(10))
    assert walked.by_task["escalated"] == walked.by_task["brainstorm"] == (BETA_COMMAND, ALPHA2)


def test_each_household_walks_its_own_choices() -> None:
    got = layered(Choices({1: {"chat": Choice("beta", "m1")}, 2: {"chat": Choice("alpha", "m2")}}, {10: 1, 20: 2}))
    assert settle(got.for_call(10)).by_task["chat"][0] == BETA1
    assert settle(got.for_call(20)).by_task["chat"][0] == ALPHA2


def test_options_are_the_tasks_own_routes_then_the_other_household_tasks_new_models() -> None:
    got = layered(Choices({1: {"chat": Choice("beta", "m1")}}))
    shown = {t.task: t for t in settle(got.choices(1))}
    assert list(shown) == ["command", "chat", "brainstorm", "action_judge"]
    assert shown["chat"].options == (ALPHA1, BETA1, ALPHA2)
    assert shown["command"].options == (BETA_COMMAND, ALPHA1, ALPHA2)
    assert shown["chat"].chosen == Choice("beta", "m1") and shown["command"].chosen is None
    judge = shown["action_judge"]
    assert (judge.household, judge.chosen, judge.options) == (False, None, ())
    assert judge.routes == got.deployment().by_task["action_judge"]


def test_options_whose_provider_is_unwired_are_not_offered() -> None:
    shown = {t.task: t for t in settle(layered(Choices(), frozenset({"alpha"})).choices(1))}
    assert shown["chat"].options == (ALPHA1, ALPHA2)


@pytest.mark.parametrize(("task", "choice", "wired", "why"), [
    ("chat", Choice("beta", "m1"), {"alpha", "beta"}, None),
    ("chat", None, {"alpha"}, None),
    ("action_judge", Choice("alpha", "m1"), {"alpha", "beta"}, "not_household"),
    ("action_judge", None, {"alpha", "beta"}, "not_household"),
    ("memory_write", Choice("alpha", "m1"), {"alpha", "beta"}, "not_household"),
    ("chat", Choice("alpha", "m9"), {"alpha", "beta"}, "not_offered"),
    ("chat", Choice("gamma", "m1"), {"alpha", "beta", "gamma"}, "not_offered"),
    ("chat", Choice("beta", "m1"), {"alpha"}, "unwired"),
])
def test_refusal(task: Any, choice: Choice | None, wired: set[str], why: str | None) -> None:
    assert layered(Choices(), frozenset(wired)).refusal(task, choice) == why


def test_a_choice_no_longer_offered_is_dropped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    got = layered(Choices({1: {"chat": Choice("alpha", "m9")}}, {10: 1}))
    assert settle(got.for_call(10)) == got.deployment()
    assert events(caplog, "inference.choice_dropped") == [
        {"household": 1, "task": "chat", "provider": "alpha", "model": "m9", "reason": "not_offered"}]


def test_a_choice_whose_provider_lost_its_key_stays_first_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    got = layered(Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1}), frozenset({"alpha"}))
    assert settle(got.for_call(10)).by_task["chat"][0] == BETA1
    assert events(caplog, "inference.choice_unwired") == [
        {"household": 1, "task": "chat", "provider": "beta", "model": "m1"}]


def test_a_choice_made_elsewhere_reaches_calls_within_the_bound_and_no_sooner() -> None:
    clock = Clock()
    choices = Choices(homes={10: 1})
    got = layered(choices, clock=clock)
    assert settle(got.for_call(10)) == got.deployment()
    choices.stored[1] = {"chat": Choice("beta", "m1")}
    clock.advance(29)
    assert settle(got.for_call(10)) == got.deployment()
    clock.advance(1)
    assert settle(got.for_call(10)).by_task["chat"][0] == BETA1
    del choices.stored[1]
    clock.advance(30)
    assert settle(got.for_call(10)) == got.deployment()
    assert choices.reads == 3


def test_a_failed_read_keeps_what_was_built_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    clock = Clock()
    choices = Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1})
    got = layered(choices, clock=clock)
    settle(got.for_call(10))
    choices.down = True
    clock.advance(30)
    assert settle(got.for_call(10)).by_task["chat"][0] == BETA1
    assert events(caplog, "inference.choices_unreadable") == [{}]


def test_before_any_read_succeeds_every_call_walks_the_deployments_routes() -> None:
    choices = Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1})
    choices.down = True
    got = layered(choices)
    assert settle(got.for_call(10)) == got.deployment()


def test_a_conversation_whose_household_cannot_be_read_walks_the_deployments_routes() -> None:
    clock = Clock()
    choices = Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1})
    got = layered(choices, clock=clock)
    settle(got.for_call(None))
    choices.down = True
    assert settle(got.for_call(10)) == got.deployment()


def test_a_conversations_household_is_read_once() -> None:
    choices = Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1})
    got = layered(choices)
    settle(got.for_call(10))
    settle(got.for_call(10))
    assert choices.lookups == 1


def test_a_household_task_that_waits_for_its_first_route_still_waits_with_a_choice() -> None:
    source = data()
    source["tasks"]["chat"]["fallback"] = False
    got = layered(Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1}), source=source)
    assert got.deployment().by_task["chat"] == (ALPHA1,)
    assert settle(got.for_call(10)).by_task["chat"] == (BETA1,)


def test_deployment_data_that_does_not_parse_is_refused() -> None:
    source = data()
    source["tasks"]["action_judge"] = {"household": True, "routes": [raw("alpha", "m1")]}
    with pytest.raises(ValueError):
        layered(Choices(), source=source)
