"""`tool_loop` against the real clock, with a model step that really sleeps: once a holdable turn passes `hold_after_s`
while a step is still running and an earlier round carried an aside, that aside is returned as `Held` by `aside_budget`
at the budget; the step is neither cancelled nor asked again, and `resume` takes its result as the round's step."""

import asyncio
import time

import pytest

from ashley.channels import aside
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held, answer, resume
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls
from ashley.inference.reply import Reply
from inference_support import settle
from turns_support import FakeInference, OTHER_SPEC, SPEC, T, World, world as world
from ashley import services

HISTORY = (Message("person", "compare the last three movies' reviews"),)
SYSTEM = {"default": SystemPrompt("you are her")}
TOOLS = (SPEC, OTHER_SPEC)
BUDGET = 0.2
SLOW = 1.0
MARGIN = 0.15
LIMITS = Limits(max_tool_rounds=6, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0,
                hold_after_s=BUDGET, deadline_s=40)
FINAL = Reply(spoken="The second one did best.", text="The second one did best.")
LOOKING = "Taking a look."


class Lagging(FakeInference):
    """`FakeInference` whose n-th step sleeps `lags[n]` seconds (0 past the list) before it answers."""

    def __init__(self, lags: list[float]) -> None:
        super().__init__()
        self.lags = lags
        self.began = 0

    async def step(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T | ToolCalls:
        n, self.began = self.began, self.began + 1
        await asyncio.sleep(self.lags[n] if n < len(self.lags) else 0.0)
        return await super().step(task, prompt, output, conversation_id=conversation_id)


def looks(round_: int) -> ToolCalls:
    return ToolCalls((ToolCall(f"r{round_}", SPEC.name, {"q": round_, aside.FIELD: LOOKING}),))


def lagging(world: World, lags: list[float], script: list[Reply | ToolCalls | Exception]) -> Lagging:
    inference = Lagging(lags)
    inference.script = script
    services.register(Inference, inference)
    return inference


async def held_then_answered(world: World) -> tuple[Answer | Held, float, Answer | None]:
    started = time.perf_counter()
    got = await answer("chat", SYSTEM, HISTORY, TOOLS, LIMITS, 7, hold=True, source=world.tools, started=started)
    at = time.perf_counter() - started
    later = await resume(got, "chat", SYSTEM, TOOLS, LIMITS, 7, source=world.tools, started=started) \
        if isinstance(got, Held) else None
    return got, at, later


def test_a_step_running_past_the_budget_holds_at_the_budget_with_the_earlier_aside(world: World) -> None:
    lagging(world, [0.0, SLOW], [looks(0), FINAL])
    got, at, _ = settle(held_then_answered(world))
    assert isinstance(got, Held) and got.by == "aside_budget"
    assert got.reply == Reply(answers=False, spoken=LOOKING, text=LOOKING)
    assert BUDGET <= at < BUDGET + MARGIN


def test_the_held_step_is_not_cancelled_and_its_result_is_the_answer(world: World) -> None:
    inference = lagging(world, [0.0, SLOW], [looks(0), FINAL])
    got, _, later = settle(held_then_answered(world))
    assert isinstance(got, Held) and got.stepping is not None and later is not None
    assert not got.stepping.future.cancelled()
    assert later.reply == FINAL and (later.rounds, later.calls) == (1, 1)
    assert inference.began == 2 and len(inference.asked) == 2


def test_a_held_step_that_asks_for_tools_goes_on_to_run_them_and_step_again(world: World) -> None:
    inference = lagging(world, [0.0, SLOW], [looks(0), looks(1), FINAL])
    got, _, later = settle(held_then_answered(world))
    assert isinstance(got, Held) and later is not None
    assert later.reply == FINAL and (later.rounds, later.calls) == (2, 2)
    assert inference.began == 3 and len(world.tools.called) == 2


def test_a_held_step_that_fails_raises_on_resume(world: World) -> None:
    lagging(world, [0.0, SLOW], [looks(0), InferenceUnavailable("down")])
    with pytest.raises(InferenceUnavailable):
        settle(held_then_answered(world))


def test_a_step_that_ends_inside_the_budget_does_not_hold(world: World) -> None:
    lagging(world, [0.0, BUDGET / 4], [looks(0), FINAL])
    got, _, _ = settle(held_then_answered(world))
    assert isinstance(got, Answer) and got.reply == FINAL


def test_a_slow_step_with_no_earlier_aside_is_not_held(world: World) -> None:
    lagging(world, [SLOW], [FINAL])
    got, at, _ = settle(held_then_answered(world))
    assert isinstance(got, Answer) and got.reply == FINAL and at >= SLOW
