"""Pins the layering contract of `HouseholdRoutes.for_call` (`household_routes`, `layered_routes`): a household with no
choices gets exactly the deployment's routes; a choice goes first with the deployment's routes after it, minus the
chosen one; a call with no conversation, no household or an unreadable store gets the deployment's; households never
touch one another; a task that follows another follows its choice; the deployment's narrowing applies to a household's
routes too."""

from dataclasses import replace
from typing import Any

import pytest
from ashley.inference import routes
from ashley.inference.layered_routes import REFRESH_S
from ashley.inference.model import Route, Task
from ashley.inference.route_choices import Choice
from ashley.inference.routes import Routes
from hypothesis import given
from hypothesis import strategies as st
from household_routes_blind_support import (
    TASK_ORDER, World, deployment_data, first, keys, own_choices, route, stubs, world)

HOUSEHOLD_TASKS: tuple[Task, ...] = ("chat", "brainstorm", "wrap_up")
OFFERED = [("a", "m1"), ("b", "m2"), ("c", "m3"), ("d", "m4")]


def with_choice(w: World, household: int, task: Task, model: tuple[str, str]) -> None:
    w.store.choices.setdefault(household, {})[task] = Choice(*model)


def expected(dep: Routes, task: Task, model: tuple[str, str]) -> tuple[Route, ...]:
    """The contract's list for a chosen model: its resolved route, then the deployment's list without it. The resolved
    route is the task's own entry for it, else the one the other household tasks give."""
    order: list[Task] = [task, *(h for h in HOUSEHOLD_TASKS if h != task)]
    pool = [r for t in order for r in dep.by_task[t]]
    chosen = next(r for r in pool if keys(r) == model)
    return (chosen, *[r for r in dep.by_task[task] if keys(r) != model])


def served(w: World, household: int = 1) -> int:
    w.store.households[10 + household] = household
    return 10 + household


def test_a_household_with_no_choices_gets_exactly_the_deployments_routes() -> None:
    w = world()
    conversation = served(w)
    assert w.for_call(conversation) == w.layered.deployment()
    assert w.for_call(conversation).by_task == w.layered.deployment().by_task


def test_the_deployments_routes_are_what_routes_parse_makes_of_its_data() -> None:
    data = deployment_data()
    w = world(data)
    assert w.layered.deployment() == routes.parse(data, dict(stubs()))


@given(task=st.sampled_from(HOUSEHOLD_TASKS), model=st.sampled_from(OFFERED))
def test_the_chosen_route_goes_first_and_the_deployments_follow_without_it(task: Task, model: tuple[str, str]) -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, task, model)
    dep, got = w.layered.deployment(), w.for_call(conversation)
    assert got.by_task[task] == expected(dep, task, model)
    assert len({keys(r) for r in got.by_task[task]}) == len(got.by_task[task]), "the chosen route is listed twice"


@given(task=st.sampled_from(HOUSEHOLD_TASKS), model=st.sampled_from(OFFERED))
def test_nothing_but_the_chosen_task_changes(task: Task, model: tuple[str, str]) -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, task, model)
    dep, got = w.layered.deployment(), w.for_call(conversation)
    moved: set[Task] = {task, "escalated"}
    assert all(got.by_task[t] == dep.by_task[t] for t in TASK_ORDER if t not in moved)
    assert replace(got, by_task=dep.by_task) == dep


def test_a_chosen_model_the_task_does_not_list_is_the_route_another_household_task_gives_it() -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, "chat", ("c", "m3"))
    got = w.for_call(conversation).by_task["chat"]
    assert [keys(r) for r in got] == [("c", "m3"), ("a", "m1"), ("b", "m2")]
    assert got[0].timeout_s == 120, "the route keeps its timeout from the deployment's entry for it"


def test_a_chosen_model_the_task_lists_keeps_that_tasks_own_timeout_and_params() -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, "chat", ("b", "m2"))
    got = w.for_call(conversation).by_task["chat"]
    assert [(r.provider, r.model, r.timeout_s) for r in got] == [("b", "m2", 30), ("a", "m1", 30)]
    assert got[1].params == w.layered.deployment().by_task["chat"][0].params


def test_the_choice_made_for_one_task_does_not_move_another() -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, "chat", ("b", "m2"))
    got = w.for_call(conversation)
    assert first(got, "brainstorm") == ("c", "m3") and first(got, "wrap_up") == ("d", "m4")


def test_a_task_that_follows_another_follows_its_chosen_model() -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, "brainstorm", ("a", "m1"))
    got = w.for_call(conversation)
    assert first(got, "brainstorm") == ("a", "m1") and first(got, "escalated") == ("a", "m1")
    assert got.by_task["escalated"] == got.by_task["brainstorm"]


def test_a_call_with_no_conversation_walks_the_deployments_routes() -> None:
    w = world()
    with_choice(w, 1, "chat", ("b", "m2"))
    assert w.for_call(None) == w.layered.deployment()


def test_a_conversation_with_no_household_walks_the_deployments_routes() -> None:
    w = world()
    with_choice(w, 1, "chat", ("b", "m2"))
    assert w.for_call(999) == w.layered.deployment()


def test_one_households_choice_never_affects_another() -> None:
    w = world()
    mine, theirs, none = served(w, 1), served(w, 2), served(w, 3)
    with_choice(w, 1, "chat", ("b", "m2"))
    with_choice(w, 2, "chat", ("a", "m1"))
    with_choice(w, 2, "wrap_up", ("b", "m2"))
    assert first(w.for_call(mine), "chat") == ("b", "m2") and first(w.for_call(mine), "wrap_up") == ("d", "m4")
    assert first(w.for_call(theirs), "chat") == ("a", "m1") and first(w.for_call(theirs), "wrap_up") == ("b", "m2")
    assert w.for_call(none) == w.layered.deployment()


def test_two_conversations_of_one_household_share_its_choices() -> None:
    w = world()
    w.store.households.update({21: 1, 22: 1})
    with_choice(w, 1, "chat", ("b", "m2"))
    assert w.for_call(21) == w.for_call(22) != w.layered.deployment()


def test_a_choice_for_a_task_that_is_not_a_households_is_not_applied() -> None:
    w = world()
    conversation = served(w)
    with_choice(w, 1, "command", ("b", "m2"))
    with_choice(w, 1, "action_judge", ("b", "m2"))
    assert w.for_call(conversation) == w.layered.deployment()


def test_the_operator_turns_a_task_off_by_giving_it_a_plain_list() -> None:
    plain = [route("a", "m1", 30), route("b", "m2", 30)]
    w = world(deployment_data(chat=plain))
    conversation = served(w)
    with_choice(w, 1, "chat", ("b", "m2"))
    assert first(w.for_call(conversation), "chat") == ("a", "m1")
    assert "chat" not in own_choices(w.layered, 1)


def test_the_deployments_narrowing_applies_to_a_households_routes_too() -> None:
    data: dict[str, Any] = deployment_data(chat={"household": True, "fallback": False, "routes": [
        route("a", "m1", 30), route("b", "m2", 30)]})
    w = world(data, narrow=routes.without_fallback)
    conversation = served(w)
    assert [keys(r) for r in w.for_call(conversation).by_task["chat"]] == [("a", "m1")]
    with_choice(w, 1, "chat", ("b", "m2"))
    w.clock[0] += REFRESH_S
    assert [keys(r) for r in w.for_call(conversation).by_task["chat"]] == [("b", "m2")]
    assert [keys(r) for r in w.layered.deployment().by_task["chat"]] == [("a", "m1")]


def test_a_deployment_that_does_not_parse_raises_value_error() -> None:
    data = deployment_data()
    tasks = dict(data["tasks"])
    del tasks["chat"]
    with pytest.raises(ValueError):
        world({"cooldown_s": 60, "tasks": tasks})


def test_the_layering_control_can_fail() -> None:
    w = world()
    conversation = served(w)
    assert w.for_call(conversation) == w.layered.deployment()
    with_choice(w, 1, "chat", ("b", "m2"))
    w.at(31)
    assert w.for_call(conversation) != w.layered.deployment(), "a choice that changed nothing would pass the tests above"
