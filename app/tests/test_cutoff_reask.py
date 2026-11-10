"""A step whose reply was cut off at the token limit is asked again once, on the same route, under `auto`, with the
`too_big` note: make the smallest real change now, or, where `bench_hand_off` is offered, hand the work to a worker. The
count lives with the turn's work, so a resumed turn does not ask twice, and a cut-off a router saw is told apart from any
other invalid output by the provider's `cut_off` field. A cut-off that is not asked again closes the turn plainly as too
big (`unsaid.TooBig`), never as a failure to retry."""

import asyncio
import logging
from dataclasses import dataclass, replace

import pytest
from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.limits import Limits
from ashley.channels.model import Inbound
from ashley.channels.steps import Steps
from ashley.inference.inference import Inference, InferenceCutOff, InferenceUnavailable
from ashley.inference.model import Message, SystemPrompt, ToolCalls
from ashley.inference.provider import ProviderFailed
from ashley.inference.reply import Reply
from contract.inference_support import FakeProvider, Step, route, router, table
from contract.inference_support import prompt as one_prompt
from contract.inference_support import settle
from pydantic import BaseModel
from respond_support import Fakes, FakeInference, calls, wired as wired

SYSTEM = {"default": SystemPrompt("s")}
HISTORY = (Message("person", "build it"),)
FINAL = Reply(spoken="Built.", text="Built.")
LIMITS = Limits(4, 8000, 1, 0)
CUT = InferenceCutOff("cut off")


def scripted(*script: ToolCalls | BaseModel | Exception) -> FakeInference:
    inference = FakeInference(script=list(script))
    services.register(Inference, inference)
    return inference


def run(wired: Fakes, steps: Steps = Steps()) -> tool_loop.Answer | tool_loop.Held:
    return asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, wired.tools.specs, LIMITS, 7,
                                        source=wired.tools, steps=steps))


@dataclass
class Counting(Steps):
    """A turn's record of the count, as `Saved` keeps it in Postgres."""

    seen: int = 0

    @property
    def cut_off(self) -> int:
        return self.seen

    async def cut(self) -> None:
        self.seen += 1


def test_a_cut_off_step_is_asked_again_once_under_auto_with_the_too_big_note(wired: Fakes,
                                                                             caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    inference = scripted(CUT, calls("lights"), FINAL)
    steps = Counting()
    got = run(wired, steps)
    assert isinstance(got, tool_loop.Answer) and got.reply.text == "Built." and got.calls == 1
    assert [p.tool_choice for p in inference.prompts] == ["auto", "auto", "auto"]
    first, again = inference.prompts[0], inference.prompts[1]
    assert again.messages == (*first.messages, unsaid.TOO_BIG) and again.tools == first.tools
    assert steps.seen == 1
    logged = [r.__dict__["fields"] for r in caplog.records if r.getMessage() == "respond.cutoff"]
    assert [(f["conversation"], f["reask"]) for f in logged] == [(7, 1)]


def too_big(got: tool_loop.Answer | tool_loop.Held) -> bool:
    return isinstance(got, tool_loop.Answer) and isinstance(got.reply, unsaid.TooBig) and got.reply.why == "too_big" \
        and got.reply.text == unsaid.TOO_BIG_LINE


def test_a_second_cut_off_closes_the_turn_as_too_big(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    inference = scripted(CUT, CUT)
    assert too_big(run(wired, Counting()))
    assert len(inference.prompts) == 2
    logged = [r.__dict__["fields"]["reask"] for r in caplog.records if r.getMessage() == "respond.cutoff"]
    assert logged == [1, 0]


def test_a_turn_that_already_asked_again_does_not_ask_on_resume(wired: Fakes) -> None:
    inference = scripted(CUT)
    steps = Counting(seen=1)
    assert too_big(run(wired, steps))
    assert len(inference.prompts) == 1 and steps.seen == 1


def test_the_count_is_in_the_checkpoint_json() -> None:
    inbound = Inbound(1, "web:1", "hi", "chat", "text", "owner", 1, False, None, "web")
    saved = Checkpoint(inbound, 1, 2, 1, SYSTEM, tool_loop.Progress(HISTORY, 0, 0), cut_off=1)
    assert loads(dumps(saved)).cut_off == 1
    assert loads(dumps(replace(saved, cut_off=0))).cut_off == 0


@pytest.mark.parametrize("failure", [InferenceUnavailable("no route answered"), ProviderFailed("invalid_output", "x")])
def test_any_other_failure_is_not_asked_again(wired: Fakes, failure: Exception) -> None:
    inference = scripted(failure)
    steps = Counting()
    with pytest.raises(Exception) as caught:
        run(wired, steps)
    assert not isinstance(caught.value, InferenceCutOff)
    assert len(inference.prompts) == 1 and steps.seen == 0


def test_a_cut_off_under_choice_none_is_not_asked_again(wired: Fakes) -> None:
    inference = scripted(calls("lights"), CUT)
    assert too_big(asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, wired.tools.specs, Limits(1, 8000, 1, 0), 7,
                                                source=wired.tools, steps=Counting())))
    assert [p.tool_choice for p in inference.prompts] == ["auto", "none"]


def cut(text: str = "x") -> Step:
    return Step(error=ProviderFailed("invalid_output", "reply cut off at the token limit", None, cut_off=True))


def test_a_router_whose_routes_were_cut_off_raises_cut_off_and_any_other_failure_does_not() -> None:
    both = [route("a"), route("b")]
    inference = router(table(both), [FakeProvider("a", [cut()]), FakeProvider("b", [cut()])])
    with pytest.raises(InferenceCutOff):
        settle(inference.step("chat", one_prompt(), Reply))
    mixed = router(table(both), [FakeProvider("a", [cut()]), FakeProvider("b", [Step(error=ProviderFailed("unavailable", "down"))])])
    with pytest.raises(InferenceCutOff):
        settle(mixed.step("chat", one_prompt(), Reply))
    plain = router(table(both), [FakeProvider("a", [Step(error=ProviderFailed("invalid_output", "bad"))]),
                                 FakeProvider("b", [Step(error=ProviderFailed("unavailable", "down"))])])
    with pytest.raises(InferenceUnavailable) as caught:
        settle(plain.step("chat", one_prompt(), Reply))
    assert not isinstance(caught.value, InferenceCutOff)
