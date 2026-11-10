"""Pins `RoutedInference` given `households` (`router`, `inference`): a text call serving a conversation walks its
household's routes, a call serving none walks the deployment's, a household's choice never fails a call whose provider
is unwired or failing, one household's choice never reaches another's call, and the router's logs carry no route
secrets or prompt text."""

import asyncio
from collections.abc import Iterable
from datetime import date

import pytest
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, Prompt, SystemPrompt, Task
from ashley.inference.prices import Prices
from ashley.inference.route_choices import Choice
from ashley.inference.router import RoutedInference
from ashley.inference.routes import without_fallback
from household_routes_blind_support import SECRET, Stub, World, deployment_data, events, logged, route, stubs, world
from pydantic import BaseModel
from speech_support import MemoryLedger

SAID = "the-person-said-something-private-1f3a"


class Answer(BaseModel):
    text: str


def prompt() -> Prompt:
    return Prompt({"default": SystemPrompt("be brief")}, (Message("person", SAID),))


def router(w: World, providers: Iterable[Stub], ledger: MemoryLedger | None = None) -> RoutedInference:
    return RoutedInference(w.layered.deployment(), providers, ledger or MemoryLedger(), Prices({}),
                           clock=lambda: w.clock[0], today=lambda: date(2026, 12, 1), households=w.layered)


def ask(r: RoutedInference, task: Task, conversation_id: int | None) -> str:
    return asyncio.run(r.generate(task, prompt(), Answer, conversation_id=conversation_id)).text


def test_a_call_serving_a_conversation_is_carried_by_its_households_chosen_model() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    assert ask(router(w, stubs().values()), "chat", 11) == "b/m2"


def test_a_call_serving_no_conversation_is_carried_by_the_deployments_first_route() -> None:
    w = world()
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    assert ask(router(w, stubs().values()), "chat", None) == "a/m1"


def test_a_household_with_no_choice_is_carried_by_the_deployments_first_route() -> None:
    w = world()
    w.store.households[11] = 1
    assert ask(router(w, stubs().values()), "chat", 11) == "a/m1"


def test_the_choice_moves_only_the_task_it_was_made_for() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    r = router(w, stubs().values())
    assert ask(r, "wrap_up", 11) == "d/m4" and ask(r, "command", 11) == "a/m1"


def test_one_households_choice_never_carries_another_households_call() -> None:
    w = world()
    w.store.households.update({11: 1, 12: 2})
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.store.choices[2] = {"chat": Choice("c", "m3")}
    r = router(w, stubs().values())
    assert [ask(r, "chat", 11), ask(r, "chat", 12), ask(r, "chat", 13)] == ["b/m2", "c/m3", "a/m1"]


def test_a_chosen_model_that_fails_falls_through_to_the_deployments_routes() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3")}
    pool = stubs()
    pool["c"] = Stub("c", fails="unavailable")
    ledger = MemoryLedger()
    assert ask(router(w, pool.values(), ledger), "chat", 11) == "a/m1"
    assert [(c.provider, c.outcome) for c in ledger.calls] == [("c", "unavailable"), ("a", "ok")]


def test_a_chosen_models_provider_that_lost_its_key_is_skipped_for_the_deployments_routes(
        info_logs: pytest.LogCaptureFixture) -> None:
    w = world(wired={"a", "b", "d"})
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3")}
    r = router(w, [s for n, s in stubs().items() if n != "c"])
    assert ask(r, "chat", 11) == "a/m1"
    skipped = events(info_logs, "inference.route_skipped")
    assert [(f["provider"], f["model"], f["reason"]) for f in skipped] == [("c", "m3", "unwired")]


def test_a_model_the_operator_no_longer_offers_never_fails_the_call() -> None:
    w = world(deployment_data(brainstorm={"household": True, "routes": [route("a", "m1", 30)]}))
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3")}
    assert ask(router(w, stubs().values()), "chat", 11) == "a/m1"


def test_a_choice_made_after_the_routers_start_carries_calls_once_the_bound_has_passed() -> None:
    w = world()
    w.store.households[11] = 1
    r = router(w, stubs().values())
    assert ask(r, "chat", 11) == "a/m1"
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.at(30)
    assert ask(r, "chat", 11) == "b/m2"


def test_a_refusal_from_the_chosen_model_is_final() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    pool = stubs()
    pool["b"] = Stub("b", refuses=True)
    with pytest.raises(InferenceRefused):
        ask(router(w, pool.values()), "chat", 11)
    assert pool["a"].calls == []


def test_every_route_failing_is_unavailable_whether_or_not_a_choice_was_made() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    pool = {n: Stub(n, fails="unavailable") for n in "abcd"}
    with pytest.raises(InferenceUnavailable):
        ask(router(w, pool.values()), "chat", 11)


def test_the_deployments_narrowing_holds_for_a_household_call() -> None:
    data = deployment_data(chat={"household": True, "fallback": False, "routes": [
        route("a", "m1", 30), route("b", "m2", 30)]})
    w = world(data, narrow=without_fallback)
    w.store.households[11] = 1
    pool = stubs()
    pool["a"] = Stub("a", fails="unavailable")
    with pytest.raises(InferenceUnavailable):
        ask(router(w, pool.values()), "chat", 11)
    assert pool["b"].calls == []


def test_the_logs_of_a_household_call_carry_no_route_params_and_no_prompt_text(
        info_logs: pytest.LogCaptureFixture) -> None:
    w = world(wired={"a", "b", "d"})
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3"), "wrap_up": Choice("zz", "gone")}
    r = router(w, [s for n, s in stubs().items() if n != "c"])
    ask(r, "chat", 11)
    ask(r, "wrap_up", 11)
    assert logged(info_logs)
    assert SECRET not in info_logs.text and SAID not in info_logs.text
