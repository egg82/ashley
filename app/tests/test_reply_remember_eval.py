"""The reply eval: each case is asked of `Inference` as her real persona would be, and a case passes when `memory` is
set exactly as the case wants: the same action and the same set of fact ids, or nothing for a case that wants no act."""

import asyncio
from collections.abc import Callable, Generator
from typing import Any

import pytest
from ashley import services
from ashley.evals import reply_remember
from ashley.inference.inference import Inference
from ashley.inference.reply import MemoryAct, Reply
from respond_support import FakeInference


@pytest.fixture
def inference() -> Generator[FakeInference]:
    made = FakeInference()
    services.register(Inference, made)
    yield made
    services.unregister(Inference)


Case = dict[str, Any]
Answer = Callable[[Case], Case | None]


def reply(act: Case | None) -> Reply:
    return Reply(spoken="s", text="t", memory=None if act is None else MemoryAct(action=act["action"], facts=tuple(act["facts"])))


def failed(inference: FakeInference, answer: Answer) -> set[str]:
    """The cases that fail when the model answers each case with `answer(case)`."""
    cases = reply_remember.load()
    inference.script = [reply(answer(c)) for c in cases]
    return {r.case_id for r in asyncio.run(reply_remember.run(1, None)) if r.passed != r.runs}


def wanting(has_facts: bool | None = None) -> set[str]:
    """The ids of the cases that want an act (with ids when `has_facts`)."""
    return {c["id"] for c in reply_remember.load() if c["act"] and (has_facts is None or bool(c["act"]["facts"]) == has_facts)}


def test_a_model_that_answers_every_case_as_wanted_fails_none(inference: FakeInference) -> None:
    assert failed(inference, lambda c: c["act"]) == set()


def test_a_model_that_never_acts_fails_exactly_the_cases_that_want_an_act(inference: FakeInference) -> None:
    assert failed(inference, lambda c: None) == wanting()


def test_a_model_that_always_keeps_fails_every_case_but_the_ones_that_want_a_keep(inference: FakeInference) -> None:
    keep: Case = {"action": "keep", "facts": []}
    assert failed(inference, lambda c: keep) == {c["id"] for c in reply_remember.load() if c["act"] != keep}


def test_the_right_action_on_the_wrong_facts_fails(inference: FakeInference) -> None:
    def wrong(case: Case) -> Case | None:
        act = case["act"]
        return act if act is None or not act["facts"] else {**act, "facts": [act["facts"][0] + 100]}
    assert failed(inference, wrong) == wanting(True)


def test_the_facts_are_compared_as_a_set_and_an_extra_one_fails(inference: FakeInference) -> None:
    def extra(case: Case) -> Case | None:
        act = case["act"]
        return act if act is None or not act["facts"] else {**act, "facts": [*act["facts"], 999]}
    assert failed(inference, extra) == wanting(True)


def test_a_case_s_remembered_facts_reach_her_prompt_as_what_she_remembers(inference: FakeInference) -> None:
    case = next(c for c in reply_remember.load() if c["id"] == "forget-a-household-fact")
    inference.script = [reply(case["act"])]
    asyncio.run(reply_remember.run(1, case["id"]))
    [(fact_id, text)] = case["remembered"]
    assert all(f"[{fact_id}] (learned Thu 1 Jan 2026 00:00) {text}" in s for s in (p.text for p in inference.prompts[0].system.values()))


def test_an_unknown_case_is_refused(inference: FakeInference) -> None:
    with pytest.raises(ValueError):
        asyncio.run(reply_remember.run(1, "nope"))
