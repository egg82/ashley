"""Directed tests of the tool loop's windows and its refusal to store a promise as her answer (`Limits.windows`,
`unsaid.STAND`). Fake inference and a hand-moved clock; the run's saved state is a recording `Steps`."""

from dataclasses import replace

from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Steps
from ashley.inference.inference import Inference
from ashley.inference.model import Message, SystemPrompt, Task, Prompt, ToolCalls
from ashley.inference.reply import Reply
from inference_support import Clock, settle
from tool_loop_blind_support import ANSWER, CID, LOOK, SPECS, Rig, Ticking, call, calls, limits, rig as rig
from pydantic import BaseModel
from typing import TypeVar

T = TypeVar("T", bound=BaseModel)

STOOD = Reply(spoken="Half of it is done.", text="Half of it is done.")


class Recording(Steps):
    def __init__(self) -> None:
        self.windows_taken = 0
        self.worked_for: list[float] = []

    @property
    def windows(self) -> int:
        return self.windows_taken

    async def windowed(self) -> None:
        self.windows_taken += 1

    async def worked(self, seconds: float) -> None:
        self.worked_for.append(seconds)


class Exact(Ticking):
    """Answers each step with the next scripted outcome exactly, whatever the tool choice, moving the clock."""

    def __init__(self, clock: Clock, script: list[Reply | ToolCalls], seconds: list[float]) -> None:
        super().__init__(clock)
        self.script = [*script]
        self.seconds = seconds

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.prompts.append(prompt)
        outcome = self.script.pop(0)
        assert not isinstance(outcome, Exception)
        self.clock.advance(self.seconds.pop(0) if self.seconds else 0.0)
        return outcome if isinstance(outcome, ToolCalls) else output.model_validate(outcome.model_dump())


def run(rig: Rig, script: list[Reply | ToolCalls], seconds: list[float], lim: Limits, steps: Steps,
        started: float | None = None) -> tuple[Answer, Exact]:
    exact = Exact(rig.clock, script, seconds)
    services.register(Inference, exact)
    out = settle(tool_loop.answer("chat", {"default": SystemPrompt("her")}, (Message("person", "go"),), SPECS, lim, CID,
                                  False, rig.source, started, rig.clock, steps))
    assert isinstance(out, Answer)
    return out, exact


def ask(id_: str) -> ToolCalls:
    return calls(call("lookup", id_))


def windows_of(count: int) -> Limits:
    return replace(limits(deadline=10, rounds=8), windows=count)


def test_a_turn_still_calling_tools_at_the_deadline_takes_a_window_and_goes_on_under_auto(rig: Rig) -> None:
    steps = Recording()
    out, exact = run(rig, [ask("a"), ask("b"), ANSWER], [11.0, 0.0, 0.0], windows_of(2), steps)
    assert [p.tool_choice for p in exact.prompts] == ["auto", "auto", "auto"]
    assert steps.windows_taken == 1 and len(rig.events("respond.window")) == 1
    assert out.closed == "answer" and out.reply == ANSWER and out.changes == 0


def test_with_no_window_left_the_deadline_closes_the_turn(rig: Rig) -> None:
    steps = Recording()
    out, exact = run(rig, [ask("a"), ANSWER], [11.0], windows_of(0), steps)
    assert out.closed == "deadline" and exact.prompts[-1].tool_choice == "none" and steps.windows_taken == 0


def test_a_closing_promise_is_asked_once_more_with_stand_and_that_reply_is_the_answer(rig: Rig) -> None:
    out, exact = run(rig, [ask("a"), LOOK, STOOD], [11.0], windows_of(0), Recording())
    assert out.reply == STOOD and out.closed == "stood" and len(exact.prompts) == 3
    assert exact.prompts[-1].messages[-1] == unsaid.STAND and exact.prompts[-1].tool_choice == "none"


def test_a_closing_answer_is_stored_with_no_second_step(rig: Rig) -> None:
    out, exact = run(rig, [ask("a"), ANSWER], [11.0], windows_of(0), Recording())
    assert out.reply == ANSWER and len(exact.prompts) == 2


def test_the_work_done_is_recorded_after_each_round(rig: Rig) -> None:
    steps = Recording()
    run(rig, [ask("a"), ask("b"), ANSWER], [3.0, 4.0], windows_of(0), steps)
    assert steps.worked_for == [3.0, 7.0]


def test_a_resumed_turn_counts_its_work_not_its_waiting(rig: Rig) -> None:
    out, exact = run(rig, [ask("a"), ANSWER], [0.0], windows_of(0), Recording(), started=rig.clock() - 6.0)
    assert out.closed == "answer" and [p.tool_choice for p in exact.prompts] == ["auto", "auto"]
    late, later = run(rig, [ANSWER], [0.0], windows_of(0), Recording(), started=rig.clock() - 400.0)
    assert late.closed == "deadline" and later.prompts[0].tool_choice == "none"


def test_only_a_brainstorm_turn_takes_windows() -> None:
    from ashley.channels import limits as shipped
    assert {kind: l.windows for kind, l in shipped.load().items()} == {"command": 0, "chat": 0, "brainstorm": 2}
