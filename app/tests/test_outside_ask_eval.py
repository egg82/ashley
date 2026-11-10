"""The outside-ask eval: each case is graded by what the model does (a call, or a judge's two fields), so a model that
behaves as wanted fails none and a model that errs one way fails exactly the cases that catch it."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services
from ashley.evals import outside_ask
from ashley.evals.outside_ask import Verdict
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.tools.outside_config import load
from pydantic import BaseModel
from respond_support import FakeInference

Case = dict[str, object]
SAYS = Reply(spoken="s", text="t")


@pytest.fixture
def inference() -> Generator[FakeInference]:
    made = FakeInference()
    services.register(Inference, made)
    yield made
    services.unregister(Inference)


def carry() -> ToolCalls:
    return ToolCalls((ToolCall("x", "carry_out", {}),))


def change() -> ToolCalls:
    return ToolCalls((ToolCall("x", "house_change", {"op": "delete", "kind": "automation"}),))


def script(inference: FakeInference, verdict: Verdict, agree: ToolCalls | Reply | None, carried: ToolCalls | Reply) -> None:
    steps: list[ToolCalls | BaseModel | Exception] = []
    for c in outside_ask.load():
        if c["kind"] == "held":
            steps += [SAYS, verdict]
        elif c["kind"] == "agree":
            steps.append((carry() if c["carry_out"] else SAYS) if agree is None else agree)
        else:
            steps.append(carried)
    inference.script = steps


def failed(inference: FakeInference) -> set[str]:
    return {r.case_id for r in asyncio.run(outside_ask.run(1, None)) if r.passed != r.runs}


def kinds(**want: object) -> set[str]:
    return {str(c["id"]) for c in outside_ask.load() if all(c.get(k) == v for k, v in want.items())}


def test_the_cases_cover_each_kind_and_both_answers_to_a_pending_block() -> None:
    assert len(kinds(kind="held")) >= 2 and len(kinds(kind="carried")) >= 2
    assert kinds(kind="agree", carry_out=True) and kinds(kind="agree", carry_out=False)


def test_a_model_that_behaves_as_wanted_fails_none(inference: FakeInference) -> None:
    script(inference, Verdict(says_it_waits=True, says_it_is_done=False), None, SAYS)
    assert failed(inference) == set()


def test_a_model_that_says_it_is_done_or_never_says_it_waits_fails_the_held_cases(inference: FakeInference) -> None:
    for verdict in (Verdict(says_it_waits=True, says_it_is_done=True), Verdict(says_it_waits=False, says_it_is_done=False)):
        script(inference, verdict, None, SAYS)
        assert failed(inference) == kinds(kind="held")


def test_a_model_that_always_carries_out_fails_the_cases_that_should_not(inference: FakeInference) -> None:
    script(inference, Verdict(says_it_waits=True, says_it_is_done=False), carry(), SAYS)
    assert failed(inference) == kinds(kind="agree", carry_out=False)


def test_a_model_that_never_carries_out_fails_the_cases_that_should(inference: FakeInference) -> None:
    script(inference, Verdict(says_it_waits=True, says_it_is_done=False), SAYS, SAYS)
    assert failed(inference) == kinds(kind="agree", carry_out=True)


def test_a_model_that_makes_a_change_from_carried_words_fails_the_carried_cases(inference: FakeInference) -> None:
    script(inference, Verdict(says_it_waits=True, says_it_is_done=False), None, change())
    assert failed(inference) == kinds(kind="carried")


def test_carry_out_is_offered_only_where_a_pending_block_is_in_the_conversation(inference: FakeInference) -> None:
    script(inference, Verdict(says_it_waits=True, says_it_is_done=False), None, SAYS)
    asyncio.run(outside_ask.run(1, None))
    offered = [(p.tool_choice, {t.name for t in p.tools}) for p in inference.prompts]
    assert any("carry_out" in names for _, names in offered) and any("carry_out" not in names for _, names in offered)
    held = next(p for p in inference.prompts if p.tool_choice == "none" and p.tools)
    assert load().held in str(held.messages)


def test_an_unknown_case_is_refused() -> None:
    with pytest.raises(ValueError):
        asyncio.run(outside_ask.run(1, "nope"))
