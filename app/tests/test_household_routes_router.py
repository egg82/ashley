"""`RoutedInference` with `households`: a text call walks its conversation's household routes, records the route that
answered (so a costlier choice shows in the spend ledger at its own price), falls through to the deployment's routes
when the chosen provider is unwired or failing, and walks the deployment's for a call serving no conversation."""

import logging
from collections.abc import Iterable

import pytest
from ashley.inference import routes
from ashley.inference.layered_routes import LayeredRoutes
from ashley.inference.reply import Reply
from ashley.inference.route_choices import Choice
from ashley.inference.router import RoutedInference
from contract.inference_support import PRICES, USAGE_COST, Clock, FakeLedger, FakeProvider, fail, prompt, settle
from household_routes_support import Choices, data, events


def routed(providers: Iterable[FakeProvider], choices: Choices) -> tuple[RoutedInference, FakeLedger]:
    wired = list(providers)
    names = frozenset(p.name for p in wired)
    layered = LayeredRoutes(data(), {p.name: p for p in wired}, lambda: names, choices, routes.without_fallback,
                            Clock(), 30.0)
    ledger = FakeLedger()
    return RoutedInference(layered.deployment(), wired, ledger, PRICES, Clock(),
                           households=layered), ledger


CHOSE_BETA = Choices({1: {"chat": Choice("beta", "m1")}}, {10: 1, 20: 2})


def test_a_call_walks_its_households_choice_and_the_ledger_records_it_at_its_price() -> None:
    alpha, beta = FakeProvider("alpha"), FakeProvider("beta")
    router, ledger = routed([alpha, beta], CHOSE_BETA)
    settle(router.generate("chat", prompt("hi"), Reply, conversation_id=10))
    assert (len(alpha.asked), len(beta.asked)) == (0, 1)
    row = ledger.rows[-1]
    assert (row.task, row.provider, row.model, row.conversation_id, row.cost_usd) == ("chat", "beta", "m1", 10, USAGE_COST)


def test_another_households_call_and_a_call_serving_no_conversation_walk_the_deployments_routes() -> None:
    alpha, beta = FakeProvider("alpha"), FakeProvider("beta")
    router, _ = routed([alpha, beta], CHOSE_BETA)
    settle(router.step("chat", prompt("hi"), Reply, conversation_id=20))
    settle(router.step("chat", prompt("hi"), Reply))
    assert (len(alpha.asked), len(beta.asked)) == (2, 0)


def test_a_chosen_provider_with_no_key_falls_through_to_the_deployments_routes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")
    alpha = FakeProvider("alpha")
    router, ledger = routed([alpha], CHOSE_BETA)
    assert settle(router.generate("chat", prompt("hi"), Reply, conversation_id=10)).text == "answer"
    assert [r.provider for r in ledger.rows] == ["alpha"]
    assert {"task": "chat", "provider": "beta", "model": "m1", "reason": "unwired"} in events(
        caplog, "inference.route_skipped")
    assert events(caplog, "inference.choice_unwired")


def test_a_chosen_provider_that_fails_falls_through_and_both_calls_are_recorded() -> None:
    alpha, beta = FakeProvider("alpha"), FakeProvider("beta", [fail("unavailable")])
    router, ledger = routed([alpha, beta], CHOSE_BETA)
    settle(router.generate("chat", prompt("hi"), Reply, conversation_id=10))
    assert [(r.provider, r.outcome) for r in ledger.rows] == [("beta", "unavailable"), ("alpha", "ok")]


def test_a_task_the_household_did_not_choose_for_walks_the_deployments_routes() -> None:
    alpha, beta = FakeProvider("alpha"), FakeProvider("beta")
    router, _ = routed([alpha, beta], CHOSE_BETA)
    settle(router.generate("brainstorm", prompt("hi"), Reply, conversation_id=10))
    assert [a.model for a in alpha.asked] == ["m2"] and not beta.asked
