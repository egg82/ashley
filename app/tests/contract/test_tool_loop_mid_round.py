"""`tool_loop` against the real clock, with a tool that really sleeps: once a holdable turn passes `hold_after_s`
while a round's calls are still running, her aside for that round is returned as `Held` by `aside_budget` at the
budget, not after the calls; the calls run on, once, and `resume` carries their results to the answer."""

import asyncio
import time
from dataclasses import dataclass, field

from ashley.channels import aside
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held, answer, resume
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue, Tools
from inference_support import settle
from turns_support import OTHER_SPEC, SPEC, World, world as world

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


@dataclass
class Sleepy(Tools):
    """Runs each call through `inner` after really sleeping `seconds`."""

    inner: Tools
    seconds: float
    seen: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return await self.inner.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        self.seen.append(call)
        await asyncio.sleep(self.seconds)
        return await self.inner.call(call)


def looks(round_: int) -> ToolCalls:
    return ToolCalls((ToolCall(f"r{round_}", SPEC.name, {"q": round_, aside.FIELD: LOOKING}),))


async def held_then_answered(tools: Sleepy) -> tuple[Answer | Held, float, Answer | None]:
    started = time.perf_counter()
    got = await answer("chat", SYSTEM, HISTORY, TOOLS, LIMITS, 7, hold=True, source=tools, started=started)
    at = time.perf_counter() - started
    later = await resume(got, "chat", SYSTEM, TOOLS, LIMITS, 7, source=tools, started=started) \
        if isinstance(got, Held) else None
    return got, at, later


def test_a_call_running_past_the_budget_holds_at_the_budget_not_after_the_call(world: World) -> None:
    world.inference.script = [looks(0), FINAL]
    got, at, _ = settle(held_then_answered(Sleepy(world.tools, SLOW)))
    assert isinstance(got, Held) and got.by == "aside_budget"
    assert got.reply == Reply(answers=False, spoken=LOOKING, text=LOOKING)
    assert BUDGET <= at < BUDGET + MARGIN


def test_a_round_held_mid_call_resumes_with_its_results_and_runs_each_call_once(world: World) -> None:
    world.inference.script = [looks(0), FINAL]
    tools = Sleepy(world.tools, SLOW)
    got, _, later = settle(held_then_answered(tools))
    assert isinstance(got, Held) and later is not None
    assert later.reply == FINAL and (later.rounds, later.calls) == (1, 1)
    assert [c.arguments for c in tools.seen] == [{"q": 0}]
    last = world.inference.asked[-1].prompt.messages
    assert isinstance(last[-1], ToolResults) and [r.call_id for r in last[-1].results] == ["r0"]


def test_a_round_that_ends_inside_the_budget_does_not_hold(world: World) -> None:
    world.inference.script = [looks(0), FINAL]
    got, _, _ = settle(held_then_answered(Sleepy(world.tools, BUDGET / 4)))
    assert isinstance(got, Answer) and got.reply == FINAL
