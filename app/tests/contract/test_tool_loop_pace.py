"""`tool_loop` against the clock: on a holdable turn every tool takes an `aside`, which never reaches the tool; once the
turn has run past `hold_after_s` with no answer, her latest aside is returned as `Held` by `aside_budget`, once, and the
turn resumes under `auto`; without an aside nothing extra goes out; past `deadline_s` the next step is the closing one,
logged `respond.deadline`. Time is a fake clock the tools move; nothing sleeps."""

from dataclasses import dataclass, field, replace
from types import SimpleNamespace

import pytest
from ashley.channels import aside
from ashley.channels import respond as respond_module
from ashley.channels import turn_tools as turn_tools_module
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held, answer, resume
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue, Tools
from inference_support import Clock, settle
from ashley.channels.model import Inbound, Outbound
from later_support import Logged, until
from turns_support import OTHER_SPEC, SPEC, World, inbound, world as world

HISTORY = (Message("person", "what's that new movie about"),)
SYSTEM = {"default": SystemPrompt("you are her")}
TOOLS = (SPEC, OTHER_SPEC)
LIMITS = Limits(max_tool_rounds=6, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0, hold_after_s=6,
                deadline_s=40)
FINAL = Reply(spoken="It's about a heist.", text="It's about a heist.")
LOOKING = "Looking that up now."
START = 1000.0


@dataclass
class Slow(Tools):
    """Runs each call through `inner`, moving `clock` on by `seconds` first."""

    inner: Tools
    clock: Clock
    seconds: float
    seen: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return await self.inner.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        self.seen.append(call)
        self.clock.advance(self.seconds)
        return await self.inner.call(call)


def looks(round_: int, said: str | None = LOOKING) -> ToolCalls:
    arguments: dict[str, object] = {"q": round_} if said is None else {"q": round_, aside.FIELD: said}
    return ToolCalls((ToolCall(f"r{round_}", SPEC.name, arguments),))


def ask(world: World, slow: Slow, hold: bool = True) -> Answer | Held:
    return settle(answer("chat", SYSTEM, HISTORY, TOOLS, LIMITS, 7, hold=hold, source=slow, started=START,
                         clock=slow.clock))


def slow(world: World, seconds: float) -> Slow:
    return Slow(world.tools, Clock(START), seconds)


def choices(world: World) -> list[str]:
    return [a.prompt.tool_choice for a in world.inference.asked]


def test_past_the_budget_her_latest_aside_is_held_once_then_the_turn_resumes_to_the_answer(world: World) -> None:
    world.inference.script = [looks(0, "Checking."), looks(1), FINAL]
    tools = slow(world, 4)
    held = ask(world, tools)
    assert isinstance(held, Held) and held.by == "aside_budget"
    assert held.reply == Reply(answers=False, spoken=LOOKING, text=LOOKING)
    assert (held.rounds, held.calls) == (2, 2) and choices(world) == ["auto", "auto"]
    world.inference.asked.clear()
    world.inference.script = [looks(2), looks(3), FINAL]
    got = settle(resume(held, "chat", SYSTEM, TOOLS, LIMITS, 7, source=tools, started=START, clock=tools.clock))
    assert isinstance(got, Answer) and got.reply == FINAL
    assert choices(world) == ["auto", "auto", "auto"] and (got.rounds, got.calls) == (4, 4)


def test_past_the_budget_with_no_aside_nothing_extra_goes_out(world: World) -> None:
    world.inference.script = [looks(0, None), looks(1, "  "), FINAL]
    got = ask(world, slow(world, 10))
    assert isinstance(got, Answer) and got.reply == FINAL and got.rounds == 2


def test_a_fast_turn_never_holds(world: World) -> None:
    world.inference.script = [looks(0), looks(1), FINAL]
    got = ask(world, slow(world, 1))
    assert isinstance(got, Answer) and got.reply == FINAL


def test_without_hold_the_budget_never_holds_and_no_aside_is_offered(world: World) -> None:
    world.inference.script = [looks(0), FINAL]
    got = ask(world, slow(world, 10), hold=False)
    assert isinstance(got, Answer)
    assert all(a.prompt.tools == TOOLS for a in world.inference.asked)


def test_on_a_holdable_turn_every_tool_requires_an_aside_the_tool_never_sees(world: World) -> None:
    world.inference.script = [looks(0), FINAL]
    tools = slow(world, 1)
    ask(world, tools)
    (first, _) = world.inference.asked
    assert [s.name for s in first.prompt.tools] == [s.name for s in TOOLS]
    for spec in first.prompt.tools:
        required, properties = spec.parameters["required"], spec.parameters["properties"]
        assert isinstance(required, list) and aside.FIELD in required
        assert isinstance(properties, dict) and aside.FIELD in properties
    assert [c.arguments for c in tools.seen] == [{"q": 0}]


def test_a_tool_with_its_own_aside_argument_keeps_it() -> None:
    own = ToolSpec("note", "n", {"type": "object", "properties": {aside.FIELD: {"type": "integer"}}})
    assert aside.offered((own,)) == (own,)


def test_past_the_deadline_the_next_step_must_answer_and_is_logged(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    world.inference.script = [looks(0), looks(1), looks(2)]
    world.inference.then = FINAL
    got = ask(world, slow(world, 15), hold=False)
    assert isinstance(got, Answer) and got.reply == FINAL
    assert choices(world) == ["auto", "auto", "auto", "none"] and got.rounds == 3
    (line,) = log.events("respond.deadline")
    assert (line["conversation"], line["rounds"], line["duration_ms"]) == ("7", "3", "45000")


def test_a_resumed_turn_is_still_bound_by_the_deadline_from_its_start(world: World) -> None:
    world.inference.script = [looks(0), looks(1)]
    tools = slow(world, 9)
    held = ask(world, tools)
    assert isinstance(held, Held) and held.by == "aside_budget"
    world.inference.asked.clear()
    world.inference.script = [looks(2), looks(3), looks(4), looks(5)]
    world.inference.then = FINAL
    got = settle(resume(held, "chat", SYSTEM, TOOLS, LIMITS, 7, source=tools, started=START, clock=tools.clock))
    assert got.reply == FINAL and choices(world) == ["auto", "auto", "auto", "auto", "none"] and got.rounds == 5


def test_web_chat_returns_her_aside_once_and_stores_the_answer_after(
        world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(START)
    monkeypatch.setattr(respond_module, "time", SimpleNamespace(perf_counter=clock))
    slow_tools = Slow(world.tools, clock, 5)

    def for_turn(_: Inbound, said: tuple[int, int] | None = None, arrival: object = None, results: object = None) -> Tools:
        return slow_tools

    monkeypatch.setattr(turn_tools_module, "for_turn", for_turn)
    world.inference.script = [looks(0), looks(1), looks(2), FINAL]
    web = replace(inbound(thread="person:11:web", kind="chat", medium="text", audience="owner", speaker_id=11,
                          shared=False, place=None), later=True, later_by="turn")
    log = Logged(capsys)

    async def scenario() -> Outbound:
        out = await respond_module.respond(web)
        await until(lambda: log.events("respond.done"))
        return out

    out = settle(scenario())
    assert out == Outbound(out.conversation_id, "text", LOOKING, follows=True)
    assert world.conversations.turns_of(out.conversation_id)[1:] == [("ashley", None, LOOKING),
                                                                      ("ashley", None, FINAL.text)]
    (held,) = log.events("respond.held")
    assert held["by"] == "aside_budget"
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto"] * 4


def test_on_a_holdable_turn_a_repeated_read_with_another_aside_is_still_not_run_again(world: World) -> None:
    world.inference.script = [looks(0, "Checking."), looks(0, "Still checking."), FINAL]
    tools = slow(world, 1)
    got = ask(world, tools)
    assert isinstance(got, Answer) and got.calls == 2
    assert [c.arguments for c in tools.seen] == [{"q": 0}]
