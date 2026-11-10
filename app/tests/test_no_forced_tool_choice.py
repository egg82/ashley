"""A reply that says it is not the answer is followed by a step every route can take. Neither brainstorm route accepts a
forced tool choice: claude-opus-5-5 answers `tool_choice` `any` with 400 "tool_choice: type "tool" and "any" are not
supported for this model.", and gemini-4-argon answers a forced call beside a JSON response format with 400 "Forced
function calling (ANY mode) with a response mime type: 'application/json' is unsupported". Both captured 2026-11-08
through the app's own adapters. The re-ask goes out under `auto` with the act note."""

import asyncio
from typing import get_args

from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.limits import Limits
from ashley.inference.inference import Inference
from ashley.inference.model import Message, SystemPrompt, ToolCalls, ToolChoice
from ashley.inference.reply import Reply
from pydantic import BaseModel
from respond_support import Fakes, FakeInference, calls, wired as wired

SYSTEM = {"default": SystemPrompt("s")}
HISTORY = (Message("person", "build it"),)
CHECKING = Reply(answers=False, spoken="Let me build that.", text="Let me build that.")
FINAL = Reply(spoken="Built.", text="Built.")
LIMITS = Limits(4, 8000, 1, 0)


def scripted(wired: Fakes, *script: ToolCalls | BaseModel | Exception) -> FakeInference:
    inference = FakeInference(script=list(script))
    services.register(Inference, inference)
    return inference


def test_no_tool_choice_forces_a_call() -> None:
    assert get_args(ToolChoice) == ("auto", "none")


def test_a_not_answer_reply_mid_turn_is_asked_again_under_auto_with_the_act_note(wired: Fakes) -> None:
    inference = scripted(wired, CHECKING, calls("lights"), FINAL)
    got = asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, wired.tools.specs, LIMITS, 7,
                                       source=wired.tools))
    assert isinstance(got, tool_loop.Answer) and got.reply.text == "Built."
    assert [p.tool_choice for p in inference.prompts] == ["auto", "auto", "auto"]
    assert inference.prompts[1].messages == (*HISTORY, unsaid.ACT) and unsaid.ACT not in got.entries


def test_a_line_held_as_not_the_answer_resumes_under_auto_with_the_act_note(wired: Fakes) -> None:
    inference = scripted(wired, calls("lights"), FINAL)
    held = tool_loop.Held(CHECKING, HISTORY, 0, 0)
    got = asyncio.run(tool_loop.resume(held, "brainstorm", SYSTEM, wired.tools.specs, LIMITS, 7,
                                       source=wired.tools))
    assert got.reply.text == "Built."
    assert [p.tool_choice for p in inference.prompts] == ["auto", "auto"]
    assert inference.prompts[0].messages == (*HISTORY, unsaid.ACT)
