"""The owed eval: each case is asked of `Inference` as her real persona would be, with the sources the case says are out
of reach, and passes when `owed` is the source it wants or null."""

import asyncio
from collections.abc import Callable, Generator

import pytest
from ashley import services
from ashley.evals import reply_owed
from ashley.inference.inference import Inference
from ashley.inference.reply import Reply
from respond_support import FakeInference

Case = dict[str, object]


@pytest.fixture
def inference() -> Generator[FakeInference]:
    made = FakeInference()
    services.register(Inference, made)
    yield made
    services.unregister(Inference)


def failed(inference: FakeInference, answer: Callable[[Case], str | None]) -> set[str]:
    cases = reply_owed.load()
    inference.script = [Reply(spoken="s", text="t", owed=answer(c)) for c in cases]
    return {r.case_id for r in asyncio.run(reply_owed.run(1, None)) if r.passed != r.runs}


def wanting() -> set[str]:
    return {str(c["id"]) for c in reply_owed.load() if c["owed"]}


def test_the_cases_cover_an_owed_and_each_kind_of_null() -> None:
    assert len(wanting()) >= 2 and len(reply_owed.load()) - len(wanting()) >= 4


def test_a_model_that_answers_every_case_as_wanted_fails_none(inference: FakeInference) -> None:
    assert failed(inference, lambda c: str(c["owed"]) if c["owed"] else None) == set()


def test_a_model_that_never_owes_fails_exactly_the_cases_that_want_it(inference: FakeInference) -> None:
    assert failed(inference, lambda c: None) == wanting()


def test_a_model_that_always_owes_the_house_fails_every_case_that_wants_null_or_another_source(
        inference: FakeInference) -> None:
    assert failed(inference, lambda c: "house") == {str(c["id"]) for c in reply_owed.load() if c["owed"] != "house"}


def test_the_sources_out_of_reach_reach_her_prompt(inference: FakeInference) -> None:
    inference.script = [Reply(spoken="s", text="t")]
    asyncio.run(reply_owed.run(1, "list-ask-while-house-down"))
    assert "can't reach the house" in inference.prompts[0].system["default"].text


def test_an_unknown_case_is_refused() -> None:
    with pytest.raises(ValueError):
        asyncio.run(reply_owed.run(1, "nope"))
