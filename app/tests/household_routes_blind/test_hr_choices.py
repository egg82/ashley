"""Pins `HouseholdRoutes.refusal` and `HouseholdRoutes.choices` (`household_routes`): which choices may be made (a
household task, one of the deployment's own routes, a provider wired now), and what the room shows for every task."""

import asyncio

import pytest
from ashley.inference import routes
from ashley.inference.household_routes import Refusal
from ashley.inference.model import Task
from ashley.inference.route_choices import Choice, RoutesUnavailable
from hypothesis import given
from hypothesis import strategies as st
from household_routes_blind_support import TASK_ORDER, deployment_data, keys, own_choices, route, world

HOUSEHOLD_TASKS: tuple[Task, ...] = ("chat", "brainstorm", "wrap_up")
NOT_HOUSEHOLD: tuple[Task, ...] = tuple(t for t in TASK_ORDER if t not in HOUSEHOLD_TASKS and t != "escalated")
OFFERED = [("a", "m1"), ("b", "m2"), ("c", "m3"), ("d", "m4")]


@given(task=st.sampled_from(HOUSEHOLD_TASKS), model=st.sampled_from(OFFERED))
def test_an_offered_model_on_a_wired_provider_may_be_chosen_for_any_household_task(task: Task,
                                                                                    model: tuple[str, str]) -> None:
    assert world().layered.refusal(task, Choice(*model)) is None


@given(task=st.sampled_from(HOUSEHOLD_TASKS))
def test_clearing_a_household_tasks_choice_is_always_allowed(task: Task) -> None:
    assert world().layered.refusal(task, None) is None


@given(task=st.sampled_from(NOT_HOUSEHOLD), model=st.sampled_from(OFFERED + [("zz", "nope")]) | st.none())
def test_a_task_that_is_not_a_households_is_refused_whatever_the_choice(task: Task, model: tuple[str, str] | None) -> None:
    refused: Refusal | None = world().layered.refusal(task, None if model is None else Choice(*model))
    assert refused == "not_household"


@given(task=st.sampled_from(HOUSEHOLD_TASKS),
       model=st.sampled_from([("a", "other-model"), ("zz", "m1"), ("a", "M1"), ("m1", "a")]))
def test_a_model_the_deployment_does_not_offer_is_refused_as_not_offered(task: Task, model: tuple[str, str]) -> None:
    assert world().layered.refusal(task, Choice(*model)) == "not_offered"


def test_an_offered_model_whose_provider_is_not_wired_is_refused_as_unwired() -> None:
    w = world(wired={"a", "b"})
    assert w.layered.refusal("chat", Choice("c", "m3")) == "unwired"
    assert w.layered.refusal("chat", Choice("a", "m1")) is None


def test_refusal_follows_the_providers_wired_at_that_moment() -> None:
    w = world()
    assert w.layered.refusal("chat", Choice("c", "m3")) is None
    w.wired.discard("c")
    assert w.layered.refusal("chat", Choice("c", "m3")) == "unwired"
    w.wired.add("c")
    assert w.layered.refusal("chat", Choice("c", "m3")) is None


def test_action_judge_is_never_a_households_even_when_the_operators_file_flags_it() -> None:
    flagged = deployment_data(action_judge={"household": True, "routes": [route("a", "m1"), route("b", "m2")]})
    with pytest.raises(ValueError):
        world(flagged)
    with pytest.raises(ValueError):
        routes.parse(flagged, {})
    assert "action_judge" in routes.NEVER_HOUSEHOLD
    assert world().layered.refusal("action_judge", Choice("a", "m1")) == "not_household"
    assert world().layered.refusal("action_judge", None) == "not_household"


def test_the_room_lists_each_household_task_in_task_order_then_action_judge() -> None:
    shown = asyncio.run(world().layered.choices(1))
    assert [c.task for c in shown] == ["chat", "brainstorm", "wrap_up", "action_judge"]
    assert [c.task for c in shown][:-1] == [t for t in TASK_ORDER if t in HOUSEHOLD_TASKS]


def test_a_household_task_shows_the_deployments_routes_and_the_options_it_may_choose() -> None:
    w = world()
    dep = w.layered.deployment()
    chat = own_choices(w.layered, 1)["chat"]
    assert chat.household and chat.chosen is None
    assert chat.routes == dep.by_task["chat"]
    assert chat.options[: len(chat.routes)] == chat.routes, "the task's own routes lead its options"
    assert sorted(keys(r) for r in chat.options) == sorted(OFFERED)
    assert len(chat.options) == 4, "an option another task also lists appears once"


def test_options_are_the_routes_a_choice_would_be_accepted_for_and_only_those() -> None:
    w = world(wired={"a", "b", "d"})
    for shown in own_choices(w.layered, 1).values():
        accepted = {m for m in OFFERED
                    if shown.household and w.layered.refusal(shown.task, Choice(*m)) is None}
        assert {keys(r) for r in shown.options} == accepted, shown.task
    assert ("c", "m3") not in {keys(r) for r in own_choices(w.layered, 1)["chat"].options}


def test_action_judge_is_shown_but_not_chosen() -> None:
    w = world()
    w.store.choices[1] = {"action_judge": Choice("b", "m2")}
    judge = own_choices(w.layered, 1)["action_judge"]
    assert not judge.household and judge.options == () and judge.chosen is None
    assert judge.routes == w.layered.deployment().by_task["action_judge"]


def test_the_room_shows_the_households_own_choice_and_not_anothers() -> None:
    w = world()
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.store.choices[2] = {"chat": Choice("a", "m1"), "wrap_up": Choice("b", "m2")}
    mine, theirs = own_choices(w.layered, 1), own_choices(w.layered, 2)
    assert mine["chat"].chosen == Choice("b", "m2") and mine["wrap_up"].chosen is None
    assert theirs["chat"].chosen == Choice("a", "m1") and theirs["wrap_up"].chosen == Choice("b", "m2")
    assert own_choices(w.layered, 3)["chat"].chosen is None


def test_the_room_reads_the_store_not_the_cache_so_a_choice_just_written_is_shown() -> None:
    w = world()
    assert w.for_call(None) == w.layered.deployment()
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    assert own_choices(w.layered, 1)["chat"].chosen == Choice("b", "m2")


def test_the_room_raises_routes_unavailable_when_the_store_cannot_be_read() -> None:
    w = world()
    w.store.down = True
    with pytest.raises(RoutesUnavailable):
        asyncio.run(w.layered.choices(1))
