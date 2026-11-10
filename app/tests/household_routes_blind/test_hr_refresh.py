"""Pins the staleness and fallback contract of `HouseholdRoutes.for_call` (`household_routes`, `layered_routes`): choices
are read again once `REFRESH_S` has passed on the injected clock, a failed read gives the deployment's routes (or keeps
what was built), a stored choice the operator no longer offers is dropped, and one whose provider lost its key stays
applied but falls through; each of those is an event with ids and counts and nothing else."""

import pytest
from ashley.inference.layered_routes import REFRESH_S
from ashley.inference.route_choices import Choice
from household_routes_blind_support import SECRET, deployment_data, events, first, keys, logged, route, world


def test_the_stated_bound_is_thirty_seconds() -> None:
    assert REFRESH_S == 30.0


def test_the_first_call_reads_the_store() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    assert first(w.for_call(11), "chat") == ("b", "m2")


def test_a_choice_reaches_a_call_once_the_bound_has_passed() -> None:
    w = world()
    w.store.households[11] = 1
    assert first(w.for_call(11), "chat") == ("a", "m1")
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.at(REFRESH_S)
    assert first(w.for_call(11), "chat") == ("b", "m2")


def test_a_cleared_choice_is_gone_once_the_bound_has_passed() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    assert first(w.for_call(11), "chat") == ("b", "m2")
    w.store.choices[1] = {}
    w.at(REFRESH_S + 0.5)
    assert w.for_call(11) == w.layered.deployment()


def test_the_choices_are_read_once_per_bound_not_once_per_call() -> None:
    w = world()
    w.store.households.update({11: 1, 12: 2})
    for i in range(20):
        w.at(i * 0.5)
        w.for_call(11 + i % 2)
    assert w.store.all_reads == 1
    w.at(REFRESH_S + 1)
    w.for_call(11)
    assert w.store.all_reads == 2


def test_a_choice_made_for_another_household_is_seen_on_the_same_refresh() -> None:
    w = world()
    w.store.households.update({11: 1, 12: 2})
    w.for_call(11)
    w.store.choices.update({1: {"chat": Choice("b", "m2")}, 2: {"wrap_up": Choice("b", "m2")}})
    w.at(REFRESH_S)
    assert first(w.for_call(11), "chat") == ("b", "m2") and first(w.for_call(11), "wrap_up") == ("d", "m4")
    assert first(w.for_call(12), "wrap_up") == ("b", "m2") and first(w.for_call(12), "chat") == ("a", "m1")


def test_before_any_read_succeeds_every_call_walks_the_deployments_routes(
        info_logs: pytest.LogCaptureFixture) -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.store.down = True
    assert w.for_call(11) == w.layered.deployment() and w.for_call(None) == w.layered.deployment()
    assert events(info_logs, "inference.choices_unreadable")


def test_a_read_that_fails_keeps_what_was_built_and_never_raises(info_logs: pytest.LogCaptureFixture) -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    assert first(w.for_call(11), "chat") == ("b", "m2")
    w.store.down = True
    w.at(REFRESH_S * 3)
    assert first(w.for_call(11), "chat") == ("b", "m2")
    assert events(info_logs, "inference.choices_unreadable")


def test_a_failed_read_is_tried_again_and_the_store_coming_back_is_seen() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.store.down = True
    assert w.for_call(11) == w.layered.deployment()
    w.store.down = False
    w.at(REFRESH_S * 2)
    assert first(w.for_call(11), "chat") == ("b", "m2")


def test_a_failed_household_lookup_gives_the_deployments_routes_and_does_not_raise() -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("b", "m2")}
    w.for_call(11)
    w.store.down = True
    assert w.for_call(12) == w.layered.deployment()


def test_a_choice_the_operator_no_longer_offers_is_dropped_and_logged(info_logs: pytest.LogCaptureFixture) -> None:
    w = world(deployment_data(chat={"household": True, "routes": [route("a", "m1", 30), route("b", "m2", 30)]},
                              brainstorm={"household": True, "routes": [route("a", "m1", 30)]}))
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3"), "wrap_up": Choice("b", "m2")}
    got = w.for_call(11)
    assert first(got, "chat") == ("a", "m1"), "a dropped choice is not applied"
    assert first(got, "wrap_up") == ("b", "m2"), "a choice that is still offered is"
    dropped = events(info_logs, "inference.choice_dropped")
    assert len(dropped) == 1 and dropped[0]["household"] == 1 and dropped[0]["task"] == "chat"


def test_a_choice_whose_provider_lost_its_key_stays_applied_and_is_logged_once_per_refresh(
        info_logs: pytest.LogCaptureFixture) -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3")}
    w.wired.discard("c")
    got = w.for_call(11)
    assert [keys(r) for r in got.by_task["chat"]] == [("c", "m3"), ("a", "m1"), ("b", "m2")], "its route is still listed"
    for _ in range(5):
        w.for_call(11)
    unwired = events(info_logs, "inference.choice_unwired")
    assert len(unwired) == 1 and unwired[0]["household"] == 1 and unwired[0]["task"] == "chat"
    w.at(REFRESH_S)
    w.for_call(11)
    assert len(events(info_logs, "inference.choice_unwired")) == 2


def test_a_choice_whose_provider_is_wired_again_is_no_longer_logged(info_logs: pytest.LogCaptureFixture) -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("c", "m3")}
    w.wired.discard("c")
    w.for_call(11)
    w.wired.add("c")
    w.at(REFRESH_S)
    w.for_call(11)
    assert len(events(info_logs, "inference.choice_unwired")) == 1


def test_a_household_that_never_chose_logs_nothing_about_choices(info_logs: pytest.LogCaptureFixture) -> None:
    w = world()
    w.store.households[11] = 1
    w.for_call(11)
    assert not [e for e, _ in logged(info_logs) if e.startswith("inference.choice")]


def test_the_choice_events_carry_ids_and_names_and_never_a_routes_params(info_logs: pytest.LogCaptureFixture) -> None:
    w = world()
    w.store.households[11] = 1
    w.store.choices[1] = {"chat": Choice("zz", "gone"), "wrap_up": Choice("d", "m4")}
    w.wired.discard("d")
    w.for_call(11)
    w.store.down = True
    w.at(REFRESH_S)
    w.for_call(11)
    seen = [(e, f) for e, f in logged(info_logs) if e.startswith("inference.choice")]
    assert {e for e, _ in seen} >= {"inference.choice_dropped", "inference.choice_unwired", "inference.choices_unreadable"}
    assert SECRET not in info_logs.text
    assert not [f for _, f in seen if any(isinstance(v, dict) for v in f.values())]
