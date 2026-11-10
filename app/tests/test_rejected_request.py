"""A turn whose every route rejected the request ends with the fixed line for it as her answer, once: it is not
retried, not kept for later, and not told as her thinking being out of reach."""

import asyncio
import logging

import pytest
from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.limits import Limits
from ashley.inference.inference import Inference, InferenceRejected, InferenceUnavailable
from ashley.inference.model import Message, SystemPrompt
from respond_support import Fakes, FakeInference, wired as wired

SYSTEM = {"default": SystemPrompt("s")}
HISTORY = (Message("person", "build it"),)
LIMITS = Limits(4, 8000, 1, 0)


def rejected(wired: Fakes) -> FakeInference:
    inference = FakeInference(script=[InferenceRejected("every route rejected the request")])
    services.register(Inference, inference)
    return inference


def test_a_rejected_request_ends_the_turn_with_the_fixed_line_after_one_step(wired: Fakes,
                                                                              caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    inference = rejected(wired)
    got = asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, wired.tools.specs, LIMITS, 7, source=wired.tools))
    assert isinstance(got, tool_loop.Answer) and got.reply == unsaid.rejected()
    assert len(inference.prompts) == 1 and unsaid.REJECTED != unsaid.UNREACHABLE
    ended = [r.__dict__["fields"] for r in caplog.records if r.getMessage() == "respond.ended"]
    assert [(f["reason"], f["recovery"]) for f in ended] == [("inference_rejected", "told")]


def test_a_plain_unavailable_still_raises(wired: Fakes) -> None:
    services.register(Inference, FakeInference(script=[InferenceUnavailable("no route answered")]))
    try:
        asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, wired.tools.specs, LIMITS, 7, source=wired.tools))
    except InferenceUnavailable as e:
        assert not isinstance(e, InferenceRejected)
    else:
        raise AssertionError("an unreachable model must still raise")


def test_a_resumed_line_whose_request_is_rejected_ends_with_the_fixed_line(wired: Fakes) -> None:
    rejected(wired)
    held = tool_loop.Held(unsaid.fixed(), HISTORY, 0, 0)
    got = asyncio.run(tool_loop.resume(held, "brainstorm", SYSTEM, wired.tools.specs, LIMITS, 7, source=wired.tools))
    assert got.reply == unsaid.rejected()
