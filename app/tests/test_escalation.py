"""A turn that cannot finish on its fast route goes on once on the stronger one (`ashley.channels.escalation`): at its
limits with no answer (A) or when the fast model's reply sets `escalate` (B). With `hold` the person gets the line
first and the stronger route runs after it; the escalation is recorded through `Steps`, and a turn already escalated
starts on the stronger route."""

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from ashley.channels import aside, escalation, unsaid
from ashley.channels import respond as respond_module
from ashley.channels import turn_tools as turn_tools_module
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.escalation import Escalation, Trigger
from ashley.channels.landing import Landing
from ashley.channels.limits import Limits, load, parse
from ashley.channels.model import Inbound, Outbound
from ashley.channels.tool_loop import Answer, Arrived, Held, Progress, Steps, answer, resume, resumed
from ashley.inference import routes
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue, Tools
from contract.turns_support import SPEC, World, inbound, world as world
from contract.inference_support import Clock, settle
from later_support import Logged, until

HISTORY = (Message("person", "remind me about the deposit"),)
SYSTEM = {"default": SystemPrompt("you are her")}
TOOLS = (SPEC,)
LIMITS = Limits(max_tool_rounds=3, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0, hold_after_s=6,
                deadline_s=40)
DEADLINE = replace(LIMITS, max_tool_rounds=10)
STRONG = replace(LIMITS, max_tool_rounds=5, deadline_s=300)
ESCALATION = Escalation(STRONG)
FINAL = Reply(spoken="Done.", text="Done.")
LOOKING = "Looking that up now."
START = 1000.0


@dataclass
class Slow(Tools):
    inner: Tools
    clock: Clock
    seconds: float

    async def catalogue(self) -> Catalogue:
        return await self.inner.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        self.clock.advance(self.seconds)
        return await self.inner.call(call)


class Recording(Steps):
    def __init__(self, escalated: Trigger | None = None) -> None:
        self.seen: list[Trigger] = []
        self._escalated: Trigger | None = escalated

    @property
    def escalated(self) -> Trigger | None:
        return self._escalated

    async def escalate(self, trigger: Trigger) -> None:
        self.seen.append(trigger)


def looks(round_: int, said: str | None = LOOKING) -> ToolCalls:
    arguments: dict[str, object] = {"q": round_} if said is None else {"q": round_, aside.FIELD: said}
    return ToolCalls((ToolCall(f"r{round_}", SPEC.name, arguments),))


def sayings(seconds: float, world: World) -> Slow:
    return Slow(world.tools, Clock(START), seconds)


def ask(world: World, tools: Slow, hold: bool = True, steps: Steps = Steps(), esc: Escalation | None = ESCALATION,
        limits: Limits = LIMITS) -> Answer | Held:
    return settle(answer("chat", SYSTEM, HISTORY, TOOLS, limits, 7, hold=hold, source=tools, started=START,
                         clock=tools.clock, steps=steps, escalation=esc))


def go_on(held: Held, tools: Slow, steps: Steps = Steps(), limits: Limits = LIMITS) -> Answer:
    return settle(resume(held, "chat", SYSTEM, TOOLS, limits, 7, source=tools, started=START, clock=tools.clock,
                         steps=steps, escalation=ESCALATION))


def tasks(world: World) -> list[str]:
    return [a.task for a in world.inference.asked]


def test_at_its_round_limit_the_turn_is_held_on_her_aside_and_goes_on_on_the_stronger_route(world: World) -> None:
    world.inference.script = [looks(0), looks(1), looks(2), FINAL]
    tools, steps = sayings(1, world), Recording()
    held = ask(world, tools, steps=steps)
    assert isinstance(held, Held) and held.by == "escalate" and held.trigger == "a"
    assert held.reply == aside.holding(LOOKING) and (held.rounds, held.calls) == (3, 3)
    assert tasks(world) == ["chat"] * 3 and steps.seen == ["a"]
    got = go_on(held, tools)
    assert got.reply == FINAL and tasks(world) == ["chat"] * 3 + ["escalated"] and got.rounds == 3
    assert world.inference.asked[-1].prompt.tool_choice == "auto"


def test_past_the_deadline_after_the_held_line_it_goes_on_at_once_and_is_logged(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    world.inference.script = [looks(0), looks(1), looks(2), FINAL]
    tools = sayings(15, world)
    held = ask(world, tools, limits=DEADLINE)
    assert isinstance(held, Held) and held.by == "aside_budget"
    got = go_on(held, tools, limits=DEADLINE)
    assert got.reply == FINAL and tasks(world) == ["chat", "chat", "chat", "escalated"]
    (line,) = log.events("respond.escalated")
    assert line == {**line, "conversation": "7", "trigger": "a", "rounds": "3", "from_route": "chat",
                    "to_route": "escalated", "duration_ms": "45000"}
    assert log.events("respond.deadline") == []


def test_a_reply_setting_escalate_holds_its_line_and_the_same_round_is_asked_on_the_stronger_route(world: World) -> None:
    world.inference.script = [Reply(escalate="Let me think that through.", spoken="x", text="x"), FINAL]
    tools, steps = sayings(1, world), Recording()
    held = ask(world, tools, steps=steps)
    assert isinstance(held, Held) and held.by == "escalate" and held.trigger == "b" and steps.seen == ["b"]
    assert held.reply == aside.holding("Let me think that through.") and (held.rounds, held.calls) == (0, 0)
    got = go_on(held, tools)
    assert got.reply == FINAL and tasks(world) == ["chat", "escalated"] and got.rounds == 0


def test_a_turn_that_may_not_hold_goes_on_at_once_for_either_trigger(world: World) -> None:
    world.inference.script = [Reply(escalate="One moment.", spoken="x", text="x"), FINAL]
    got = ask(world, sayings(1, world), hold=False)
    assert isinstance(got, Answer) and got.reply == FINAL and tasks(world) == ["chat", "escalated"]
    world.inference.asked.clear()
    world.inference.script = [looks(0), looks(1), looks(2), FINAL]
    got = ask(world, sayings(1, world), hold=False)
    assert isinstance(got, Answer) and got.reply == FINAL and tasks(world) == ["chat"] * 3 + ["escalated"]


def test_at_its_limit_with_no_aside_to_say_a_holding_turn_closes_on_the_fast_route_as_before(world: World) -> None:
    world.inference.script = [looks(0, None), looks(1, None), looks(2, None)]
    world.inference.then = FINAL
    got = ask(world, sayings(1, world))
    assert isinstance(got, Answer) and got.reply == FINAL and tasks(world) == ["chat"] * 4
    assert world.inference.asked[-1].prompt.tool_choice == "none"


def test_a_turn_past_its_deadline_before_any_call_has_nothing_to_escalate_from(world: World) -> None:
    world.inference.then = FINAL
    tools = sayings(1, world)
    got = settle(answer("chat", SYSTEM, HISTORY, TOOLS, LIMITS, 7, hold=False, source=tools, started=START - 100,
                        clock=tools.clock, escalation=ESCALATION))
    assert isinstance(got, Answer) and tasks(world) == ["chat"]


def test_a_turn_whose_page_moved_to_a_bench_no_longer_escalates(world: World) -> None:
    arrived = [Arrived(TOOLS, SYSTEM, LIMITS, "brainstorm")]

    async def arrive(_: object) -> Arrived | None:
        return arrived.pop() if len(world.inference.asked) == 1 and arrived else None

    world.inference.script = [looks(0), looks(1), looks(2)]
    world.inference.then = FINAL
    tools = sayings(1, world)
    got = settle(answer("chat", SYSTEM, HISTORY, TOOLS, LIMITS, 7, hold=False, source=tools, started=START,
                        clock=tools.clock, arrive=arrive, escalation=ESCALATION))
    assert isinstance(got, Answer) and tasks(world) == ["chat", "brainstorm", "brainstorm", "brainstorm"]


def test_without_an_escalation_a_reply_setting_escalate_is_an_ordinary_reply(world: World) -> None:
    said = Reply(escalate="One moment.", spoken="Hello.", text="Hello.")
    world.inference.script = [said]
    got = ask(world, sayings(1, world), esc=None)
    assert isinstance(got, Answer) and got.reply == said and tasks(world) == ["chat"]


def test_it_escalates_once_and_the_stronger_route_ends_the_turn_at_its_own_limits(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    world.inference.script = [looks(i) for i in range(5)]
    world.inference.then = FINAL
    got = ask(world, sayings(1, world), hold=False)
    assert isinstance(got, Answer) and got.reply == FINAL
    assert tasks(world) == ["chat"] * 3 + ["escalated"] * 3
    last = world.inference.asked[-1].prompt
    assert last.tool_choice == "none" and last.messages[-1] == unsaid.ASK
    assert len(log.events("respond.escalated")) == 1


def test_a_stronger_route_reply_setting_escalate_does_not_escalate_again(world: World) -> None:
    again = Reply(escalate="Once more.", spoken="Here.", text="Here.")
    world.inference.script = [Reply(escalate="One moment.", spoken="x", text="x"), again]
    got = ask(world, sayings(1, world), hold=False)
    assert isinstance(got, Answer) and got.reply == again and tasks(world) == ["chat", "escalated"]


def test_a_turn_recorded_as_escalated_starts_on_the_stronger_route_and_its_limits(world: World) -> None:
    world.inference.script = [looks(3), looks(4)]
    world.inference.then = FINAL
    tools = sayings(1, world)
    got = settle(resumed(Progress(HISTORY, 3, 3), "chat", SYSTEM, TOOLS, LIMITS, 7, tools, False, START, clock=tools.clock,
                         steps=Recording("a"), escalation=ESCALATION))
    assert got.reply == FINAL and set(tasks(world)) == {"escalated"} and got.rounds == 5
    assert world.inference.asked[-1].prompt.tool_choice == "none"


def test_a_turn_with_no_escalation_configured_ignores_a_recorded_one(world: World) -> None:
    world.inference.script = [FINAL]
    tools = sayings(1, world)
    got = settle(resumed(Progress(HISTORY, 0, 0), "chat", SYSTEM, TOOLS, LIMITS, 7, tools, False, START,
                         clock=tools.clock, steps=Recording("b")))
    assert got.reply == FINAL and tasks(world) == ["chat"]


def test_the_trigger_is_kept_in_the_checkpoint_and_a_bad_one_is_refused() -> None:
    plain = Checkpoint(inbound(), 5, 77, 1, SYSTEM, Progress(HISTORY, 0, 0))
    saved = replace(plain, escalated="b")
    assert loads(dumps(saved)).escalated == "b"
    assert loads(dumps(plain)).escalated is None
    with pytest.raises(ValueError):
        loads(dumps(saved).replace('"escalated": "b"', '"escalated": "c"'))


def test_only_chat_escalates_and_the_stronger_limits_keep_the_kinds_reply_length() -> None:
    shipped = load()
    assert [k for k, v in shipped.items() if v.escalates] == ["chat"]
    made = escalation.of("chat", shipped)
    assert made is not None and made.task == "escalated"
    assert made.limits == replace(shipped["brainstorm"], reply_chars=0, escalates=False)
    assert escalation.of("command", shipped) is None and escalation.of("brainstorm", shipped) is None


def test_escalates_must_be_a_flag() -> None:
    data = {k: dict(v.__dict__) for k, v in load().items()}
    data["chat"]["escalates"] = 1
    with pytest.raises(ValueError, match="chat.escalates"):
        parse(data)


def test_the_escalated_task_has_the_routes_of_brainstorm_and_a_bad_like_is_refused() -> None:
    shipped = routes.load({})
    assert shipped.for_task("escalated") == shipped.for_task("brainstorm") != ()
    one = [{"provider": "p", "model": "m", "timeout_s": 1}]
    text = {t: one for t in routes.TASKS if t != "escalated"}
    ok = routes.parse({"cooldown_s": 1, "tasks": {**text, "escalated": {"like": "chat"}}}, {})
    assert ok.for_task("escalated") == ok.for_task("chat")
    for bad in ({"like": "nothing"}, {"like": "escalated"}, {"like": 3}):
        with pytest.raises(ValueError, match="escalated.like"):
            routes.parse({"cooldown_s": 1, "tasks": {**text, "escalated": bad}}, {})


def test_a_landing_escalates_only_on_a_channel_that_takes_later_replies_and_off_a_bench(world: World) -> None:
    web = replace(inbound(thread="person:11:web", kind="chat", medium="text", audience="owner", speaker_id=11,
                          shared=False, place=None), later=True, later_by="turn")
    limits = respond_module.LIMITS
    assert Landing(web, (1, 2), limits).escalation == escalation.of("chat", limits)
    assert Landing(replace(web, later=False), (1, 2), limits).escalation is None
    assert Landing(replace(web, moved_to=4), (1, 2), limits).escalation is None
    assert Landing(replace(web, kind="command"), (1, 2), limits).escalation is None


def test_web_chat_says_the_line_then_stores_the_stronger_route_answer(
        world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(START)
    monkeypatch.setattr(respond_module, "time", SimpleNamespace(perf_counter=clock))
    slow = Slow(world.tools, clock, 0.5)

    def for_turn(_: Inbound, said: tuple[int, int] | None = None, arrival: object = None, results: object = None) -> Tools:
        return slow

    monkeypatch.setattr(turn_tools_module, "for_turn", for_turn)
    world.inference.script = [*(looks(i) for i in range(6)), FINAL]
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
    assert tasks(world) == ["chat"] * 6 + ["escalated"]
    assert [e["by"] for e in log.events("respond.held")] == ["escalate"]
    (line,) = log.events("respond.escalated")
    assert (line["trigger"], line["rounds"], line["from_route"], line["to_route"]) == ("a", "6", "chat", "escalated")
