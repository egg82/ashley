"""A call is judged once: the verdict is saved through the turn's steps before the call runs, and a runner that resumes the
turn (a new `Outside` over the same saved steps) reuses it, run or ask, whatever the judge would say now."""

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.channels.inflight import Unsaved
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.outside import Outside
from outside_ask_support import CONVERSATION, STANDING, TURN, WORDS, Fake, Memory, asked, run, said, spec
from ashley.senses.proposals import Proposals


@dataclass
class Sequenced(ActionJudge):
    """Answers each ask with the next of `answers`."""

    answers: list[Verdict]
    asked: int = 0
    seen: list[tuple[Sequence[str], View]] = field(default_factory=list[tuple[Sequence[str], View]])

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.seen.append((words, view))
        self.asked += 1
        return self.answers[min(self.asked, len(self.answers)) - 1]


class Watching(Fake):
    """Records, when a tool runs, what the saved steps held for its call."""

    def __init__(self, steps: Unsaved) -> None:
        super().__init__((spec("look", reads=True, outside=True), spec("garage")))
        self.steps, self.held_when_run = steps, False

    async def call(self, call: ToolCall) -> ToolResult:
        if call.name == "garage":
            self.held_when_run = self.steps.judgement(call.id) is not None
        return await super().call(call)


@pytest.fixture(autouse=True)
def judge_unwired() -> Generator[None]:
    services.register(Proposals, Memory())
    yield
    services.unregister(ActionJudge)


def runner(source: Fake, steps: Unsaved) -> Outside:
    outside = Outside(source, STANDING, (CONVERSATION, TURN), None, "look", None, said)
    outside.judging(steps)
    return outside


RUN = Verdict("run", "asked_directly", "You asked for it.")
ASK = Verdict("ask", "not_asked", "You did not ask.")


def test_the_verdict_is_saved_before_the_call_runs() -> None:
    async def go() -> None:
        steps = Unsaved("look")
        services.register(ActionJudge, Sequenced([RUN]))
        source = Watching(steps)
        outside = runner(source, steps)
        await outside.catalogue()
        await outside.call(asked("garage", "c9"))
        assert source.held_when_run and steps.judgement("c9") == RUN

    run(go())


def test_a_resumed_runner_runs_on_a_saved_run_and_does_not_ask_the_judge_again() -> None:
    async def go() -> None:
        steps = Unsaved("look")
        judge = Sequenced([RUN, ASK])
        services.register(ActionJudge, judge)
        first = Fake((spec("look", reads=True, outside=True), spec("garage")))
        await (r := runner(first, steps)).catalogue()
        await r.call(asked("garage", "c9"))
        second = Fake((spec("look", reads=True, outside=True), spec("garage")))
        await (r2 := runner(second, steps)).catalogue()
        await r2.call(asked("garage", "c9"))
        assert judge.asked == 1 and [c.name for c in second.ran] == ["garage"]

    run(go())


def test_a_resumed_runner_holds_on_a_saved_ask_whatever_the_judge_would_say_now() -> None:
    async def go() -> None:
        steps = Unsaved("look")
        await steps.judged("c9", ASK)
        judge = Sequenced([RUN])
        services.register(ActionJudge, judge)
        source = Fake((spec("look", reads=True, outside=True), spec("garage")))
        outside = runner(source, steps)
        await outside.catalogue()
        got = await outside.call(asked("garage", "c9"))
        assert judge.asked == 0 and source.ran == [] and "You did not ask." in got.content

    run(go())


def test_another_call_id_is_judged_afresh() -> None:
    async def go() -> None:
        steps = Unsaved("look")
        judge = Sequenced([RUN, ASK])
        services.register(ActionJudge, judge)
        source = Fake((spec("look", reads=True, outside=True), spec("garage")))
        outside = runner(source, steps)
        await outside.catalogue()
        await outside.call(asked("garage", "c1"))
        await outside.call(asked("garage", "c2"))
        assert judge.asked == 2 and [c.id for c in source.ran] == ["c1"]
        assert judge.seen[0][0] == WORDS

    run(go())
