"""A bench turn that offers `bench_hand_off` and has run past `hand_off_after_rounds` rounds or `hand_off_after_s`
seconds is told once to hand the work off (`channels.hand_off`), under tool choice `auto`; one that does not offer the
tool, or has not run that long, is never told."""

import asyncio
import dataclasses

from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.limits import Limits
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, ToolSpec
from ashley.inference.reply import Reply
from respond_support import Fakes, FakeInference, calls, wired as wired

SYSTEM = {"default": SystemPrompt("s")}
HISTORY = (Message("person", "build it"),)
FINAL = Reply(spoken="Built.", text="Built.")
LIMITS = Limits(10, 8000, 1, 0)
HAND_OFF_TOOL = ToolSpec("bench_hand_off", "hands work to a worker", {"type": "object", "properties": {}})


def told(prompt: Prompt) -> int:
    return prompt.messages.count(unsaid.HAND_OFF)


def run(wired: Fakes, limits: Limits, rounds: int, offered: bool = True, ticks: float = 0.0) -> FakeInference:
    inference = FakeInference(script=[*(calls("lights", prefix=f"r{i}-") for i in range(rounds)), FINAL])
    services.register(Inference, inference)
    now = [0.0]

    def clock() -> float:
        now[0] += ticks
        return now[0]

    tools = (*wired.tools.specs, HAND_OFF_TOOL) if offered else wired.tools.specs
    got = asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, tools, limits, 7, source=wired.tools, clock=clock))
    assert isinstance(got, tool_loop.Answer) and got.reply.text == "Built."
    return inference


def test_past_the_rounds_limit_she_is_told_once_and_the_choice_stays_auto(wired: Fakes) -> None:
    inference = run(wired, dataclasses.replace(LIMITS, hand_off_after_rounds=3), 6)
    assert [told(p) for p in inference.prompts] == [0, 0, 0, 1, 1, 1, 1]
    assert {p.tool_choice for p in inference.prompts} == {"auto"}


def test_past_the_seconds_limit_she_is_told_once(wired: Fakes) -> None:
    inference = run(wired, dataclasses.replace(LIMITS, hand_off_after_s=5), 5, ticks=2.0)
    counts = [told(p) for p in inference.prompts]
    assert counts[0] == 0 and counts[-1] == 1 and max(counts) == 1 and counts == sorted(counts)


def test_a_turn_without_the_tool_is_never_told(wired: Fakes) -> None:
    inference = run(wired, dataclasses.replace(LIMITS, hand_off_after_rounds=1, hand_off_after_s=1), 4, offered=False,
                    ticks=1.0)
    assert [told(p) for p in inference.prompts] == [0] * 5


def test_a_short_turn_is_never_told(wired: Fakes) -> None:
    inference = run(wired, dataclasses.replace(LIMITS, hand_off_after_rounds=8, hand_off_after_s=100), 3)
    assert [told(p) for p in inference.prompts] == [0] * 4


def test_the_shipped_brainstorm_limits_set_both_and_the_note_offers_the_tool() -> None:
    from ashley.channels.limits import load
    shipped = load()["brainstorm"]
    assert shipped.hand_off_after_rounds > 0 and shipped.hand_off_after_s < shipped.deadline_s
    assert "bench_hand_off" in unsaid.HAND_OFF.text


def test_unset_limits_never_tell_her(wired: Fakes) -> None:
    inference = run(wired, LIMITS, 6, ticks=50.0)
    assert [told(p) for p in inference.prompts] == [0] * 7
