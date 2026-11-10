"""`RoutedInference` with fake providers: route order, unwired and resting skips, cooldown expiry, a refusal that is
final, every failure task moving on, the arguments each provider receives, and `InferenceUnavailable` when nothing
answered."""

import pytest
from ashley.inference.model import SystemPrompt, Task
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message
from ashley.inference.provider import Failure
from ashley.inference.reply import Reply
from ashley.inference.router import RoutedInference
from inference_support import (ANY_TASK, COOLDOWN_S, FAILURES, Clock, FakeLedger, FakeProvider, Step, fail, ok,
                               outcomes, prompt, refuse, route, router, settle, table)
from pydantic import BaseModel


def ask(inference: RoutedInference, task: Task = "chat", text: str = "hello") -> Reply:
    return settle(inference.generate(task, prompt(text), Reply))


def test_the_first_route_that_answers_is_returned_and_no_later_route_is_called() -> None:
    a, b, c = FakeProvider("a", [ok("from a")]), FakeProvider("b", [ok("from b")]), FakeProvider("c")
    inference = router(table([route("a"), route("b"), route("c")]), [a, b, c])
    assert ask(inference) == Reply(spoken="from a", text="from a")
    assert (len(a.asked), len(b.asked), len(c.asked)) == (1, 0, 0)


def test_the_answer_is_shaped_as_the_asked_for_output() -> None:
    class Verdict(BaseModel):
        yes: bool

    provider = FakeProvider("a", [Step({"yes": True})])
    inference = router(table([route("a")]), [provider])
    got = settle(inference.generate("chat", prompt("is it?"), Verdict))
    assert got == Verdict(yes=True)
    assert provider.asked[0].output is Verdict


@pytest.mark.parametrize("failure", FAILURES)
def test_each_failure_kind_moves_on_to_the_next_route(failure: Failure) -> None:
    a, b = FakeProvider("a", [fail(failure)]), FakeProvider("b", [ok("from b")])
    ledger = FakeLedger()
    inference = router(table([route("a"), route("b")]), [a, b], ledger)
    assert ask(inference).text == "from b"
    assert outcomes(ledger) == [("a", "m1", failure), ("b", "m1", "ok")]


def test_routes_are_tried_in_the_configured_order() -> None:
    providers = [FakeProvider(n, [fail("error")]) for n in ("x", "y", "z")]
    ledger = FakeLedger()
    inference = router(table([route("z"), route("x", "m2"), route("y")]), providers, ledger)
    with pytest.raises(InferenceUnavailable):
        ask(inference)
    assert outcomes(ledger) == [("z", "m1", "error"), ("x", "m2", "error"), ("y", "m1", "error")]


def test_a_refusal_is_final_and_no_other_route_is_asked() -> None:
    a, b = FakeProvider("a", [refuse()]), FakeProvider("b")
    ledger = FakeLedger()
    inference = router(table([route("a"), route("b")]), [a, b], ledger)
    with pytest.raises(InferenceRefused):
        ask(inference)
    assert b.asked == []
    assert outcomes(ledger) == [("a", "m1", "refused")]


def test_a_refusal_after_an_earlier_failure_is_still_final() -> None:
    a, b, c = FakeProvider("a", [fail("unavailable")]), FakeProvider("b", [refuse()]), FakeProvider("c")
    inference = router(table([route("a"), route("b"), route("c")]), [a, b, c])
    with pytest.raises(InferenceRefused):
        ask(inference)
    assert c.asked == []


def test_a_refusal_does_not_rest_the_provider() -> None:
    a = FakeProvider("a", [refuse(), ok("again")])
    inference = router(table([route("a")]), [a])
    with pytest.raises(InferenceRefused):
        ask(inference)
    assert ask(inference).text == "again"


def test_nothing_answering_is_inference_unavailable() -> None:
    a, b = FakeProvider("a", [fail("unavailable")]), FakeProvider("b", [fail("invalid_output")])
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("a"), route("b")]), [a, b]))


def test_a_route_whose_provider_is_not_wired_is_skipped_without_a_call_or_a_ledger_row() -> None:
    b = FakeProvider("b", [ok("from b")])
    ledger = FakeLedger()
    inference = router(table([route("ghost"), route("b")]), [b], ledger)
    assert ask(inference).text == "from b"
    assert outcomes(ledger) == [("b", "m1", "ok")]


def test_every_route_unwired_is_unavailable_and_records_nothing() -> None:
    ledger = FakeLedger()
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("ghost"), route("phantom")]), [FakeProvider("b")], ledger))
    assert ledger.rows == []


def test_no_providers_at_all_is_unavailable() -> None:
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("a")]), []))


def test_a_bad_kind_is_a_value_error_before_anything_is_called_or_recorded() -> None:
    a, ledger = FakeProvider("a"), FakeLedger()
    inference = router(table([route("a")]), [a], ledger)
    with pytest.raises(ValueError):
        settle(inference.generate(ANY_TASK, prompt("hi"), Reply))
    assert a.asked == [] and ledger.rows == [] and ledger.attempts == 0


def test_each_kind_uses_its_own_routes() -> None:
    a, b = FakeProvider("a", [ok("from a")]), FakeProvider("b", [ok("from b")])
    inference = router(table([route("a")], overrides={"brainstorm": [route("b")]}), [a, b])
    assert ask(inference, "command").text == "from a"
    assert ask(inference, "brainstorm").text == "from b"
    assert [len(a.asked), len(b.asked)] == [1, 1]


def test_duplicate_provider_names_are_refused() -> None:
    with pytest.raises(ValueError):
        router(table([route("a")]), [FakeProvider("a"), FakeProvider("b"), FakeProvider("a")])


def test_providers_may_be_any_iterable_and_are_found_by_their_name() -> None:
    a = FakeProvider("a", [ok("hi")])
    assert ask(router(table([route("a")]), iter([FakeProvider("zz"), a]))).text == "hi"


# --- what each provider receives ----------------------------------------------------------------------------------


def test_a_provider_receives_the_routes_model_params_timeout_and_the_prompt_messages_in_order() -> None:
    a = FakeProvider("a")
    given = prompt("one", "two", "three")
    inference = router(table([route("a", "model-x", 7.5, params={"max_tokens": 9, "effort": "low"})]), [a])
    settle(inference.generate("chat", given, Reply))
    asked = a.asked[0]
    assert (asked.model, asked.timeout_s, asked.output) == ("model-x", 7.5, Reply)
    assert dict(asked.params) == {"max_tokens": 9, "effort": "low"}
    assert asked.messages == given.messages == (Message("person", "one"), Message("ashley", "two"),
                                                 Message("person", "three"))
    assert asked.system == SystemPrompt("be Ashley")


def test_each_route_sends_the_system_prompt_tuned_for_its_variant_else_the_default() -> None:
    a, b, c = FakeProvider("a", [fail("error")]), FakeProvider("b", [fail("error")]), FakeProvider("c")
    inference = router(table([route("a", variant="tuned"), route("b", variant="untuned"), route("c")]), [a, b, c])
    given = prompt("hi", system={"default": "base", "tuned": "for a"})
    settle(inference.generate("chat", given, Reply))
    assert (a.asked[0].system, b.asked[0].system, c.asked[0].system) == (SystemPrompt("for a"), SystemPrompt("base"), SystemPrompt("base"))


def test_two_routes_on_one_provider_make_two_calls_with_their_own_models_and_params() -> None:
    a = FakeProvider("a", [fail("error"), ok("second")])
    inference = router(table([route("a", "m1", params={"n": 1}), route("a", "m2", params={"n": 2})]), [a])
    assert ask(inference).text == "second"
    assert [(x.model, dict(x.params)) for x in a.asked] == [("m1", {"n": 1}), ("m2", {"n": 2})]


# --- resting --------------------------------------------------------------------------------------------------------


def test_a_provider_that_failed_unavailable_rests_for_the_cooldown_then_is_tried_again() -> None:
    clock = Clock()
    a, b = FakeProvider("a", [fail("unavailable"), ok("a is back")]), FakeProvider("b", [ok("from b")])
    inference = router(table([route("a"), route("b")]), [a, b], clock=clock)
    assert ask(inference).text == "from b"
    clock.advance(COOLDOWN_S - 1)
    assert ask(inference).text == "from b"
    assert len(a.asked) == 1, "still resting"
    clock.advance(2)
    assert ask(inference).text == "a is back"
    assert len(a.asked) == 2


@pytest.mark.parametrize("failure", ["invalid_output", "error"])
def test_only_unavailable_rests_a_provider(failure: Failure) -> None:
    a = FakeProvider("a", [fail(failure), ok("fine")])
    inference = router(table([route("a")]), [a])
    with pytest.raises(InferenceUnavailable):
        ask(inference)
    assert ask(inference).text == "fine"


def test_resting_is_the_providers_not_the_kinds() -> None:
    a, b = FakeProvider("a", [fail("unavailable"), ok("a again")]), FakeProvider("b", [ok("from b")])
    inference = router(table([route("a"), route("b")]), [a, b])
    assert ask(inference, "chat").text == "from b"
    assert ask(inference, "command").text == "from b"
    assert len(a.asked) == 1


def test_a_resting_provider_does_not_rest_the_others() -> None:
    a, b = FakeProvider("a", [fail("unavailable")]), FakeProvider("b", [ok("1"), ok("2"), ok("3")])
    inference = router(table([route("a")], overrides={"command": [route("b")]}), [a, b])
    with pytest.raises(InferenceUnavailable):
        ask(inference, "chat")
    assert [ask(inference, "command").text for _ in range(3)] == ["1", "2", "3"]


def test_a_second_failure_after_the_cooldown_rests_it_for_a_whole_new_cooldown() -> None:
    clock = Clock()
    a = FakeProvider("a", [fail("unavailable")])
    inference = router(table([route("a")]), [a], clock=clock)
    for expected_calls in (1, 2):
        with pytest.raises(InferenceUnavailable):
            ask(inference)
        assert len(a.asked) == expected_calls
        clock.advance(COOLDOWN_S - 1)
        with pytest.raises(InferenceUnavailable):
            ask(inference)
        assert len(a.asked) == expected_calls, "rests again from the second failure"
        clock.advance(2)


def test_a_cooldown_is_the_tables_not_a_constant() -> None:
    clock = Clock()
    a = FakeProvider("a", [fail("unavailable"), ok("back")])
    inference = router(table([route("a")], cooldown_s=5), [a], clock=clock)
    with pytest.raises(InferenceUnavailable):
        ask(inference)
    clock.advance(4)
    with pytest.raises(InferenceUnavailable):
        ask(inference)
    assert len(a.asked) == 1
    clock.advance(2)
    assert ask(inference).text == "back"


def test_a_resting_provider_is_skipped_for_every_route_that_names_it_in_the_same_call() -> None:
    a = FakeProvider("a", [fail("unavailable"), ok("second route")])
    b = FakeProvider("b", [ok("from b")])
    inference = router(table([route("a", "m1"), route("a", "m2"), route("b")]), [a, b])
    assert ask(inference).text == "from b"
    assert len(a.asked) == 1


def test_a_resting_provider_alone_is_unavailable_without_a_call() -> None:
    a = FakeProvider("a", [fail("unavailable")])
    inference = router(table([route("a")]), [a])
    for _ in range(3):
        with pytest.raises(InferenceUnavailable):
            ask(inference)
    assert len(a.asked) == 1
