"""A turn that takes the speaker's page to a bench is that bench's from then on: she is offered its tools and told to
lead on a bench she just opened, her reply is said in the bench's talk after the ask carried from chat, and chat keeps
the ask with a turn that continues on the bench. A move to anything else leaves her reply where it was."""

import asyncio
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.channels.inflight import Work
from ashley.channels.live_turn import Showing
from ashley.channels.model import Inbound
from ashley.channels.settled import Ended, settle
from ashley.channels.unsaid import unreachable
from ashley.conversations.model import NewTurn
from ashley.inference.inference import InferenceUnavailable
from ashley.live.events import ThreadTurn
from ashley.channels.respond import respond
from ashley.conversations.model import Conversation
from ashley.inference.inference import Inference, T
from ashley.inference.model import Message, Prompt, Task, ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.tools import bench_tools
from ashley.tools.bench_lead import lead
from ashley.workshop.model import Bench, Owner
from ashley.workshop.workshop import BenchView, Workshop, WorkshopUnavailable
from bench_tools_support import EPOCH, FakeWorkshop
from live_support import FakeLive
from respond_support import ALANA, HOME, FakeInference, Fakes, inbound, wired as wired

REPLY = Reply(spoken="I read them. Which should stay?", text="I read them. Which should stay?")
CHAT = replace(inbound("work on Alana comes home with me", thread="person:1:web", speaker_id=ALANA.id, kind="chat"),
               audience="owner", shared=False, place=None, channel="web", later=True, later_by="turn",
               opens_benches=True, on_page=True)
BENCH_TALK = replace(CHAT, thread="bench:9", kind="brainstorm", opens_benches=False, bench_id=9)


@dataclass
class Shop(FakeWorkshop):
    """A workshop with one open bench, 9, titled "Alana comes home"."""

    mine: tuple[int, ...] = (9,)
    opened: list[str] = field(default_factory=list[str])
    down: bool = False

    async def open(self, owner: Owner, title: str) -> Bench:
        self.opened.append(title)
        return Bench(9, owner.household_id, owner.person_id, title, EPOCH, None)

    async def open_benches(self, owner: Owner) -> list[Bench]:
        return [Bench(b, owner.household_id, owner.person_id, "Alana comes home", EPOCH, None) for b in self.mine]

    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        if self.down:
            raise WorkshopUnavailable()
        view = await super().read(owner, bench_id)
        return replace(view, bench=replace(view.bench, title="Alana comes home"))


@pytest.fixture
def shop(wired: Fakes) -> Shop:
    fake = Shop()
    services.register(Workshop, fake)
    services.register(Live, FakeLive())
    wired.tools.specs = ()
    return fake


def open_bench() -> ToolCalls:
    return ToolCalls((ToolCall("o", "open_bench", {"title": "Alana comes home"}),))


def move(to: str = "bench", **more: object) -> ToolCalls:
    return ToolCalls((ToolCall("m", "move_page", {"to": to, "bench_id": 9, **more}),))


def add_piece() -> ToolCalls:
    return ToolCalls((ToolCall("a", "bench_add", {"kind": "note", "title": "Heading home", "body": "b"}),))


def turn_in(wired: Fakes, thread: str) -> Conversation:
    found = asyncio.run(wired.conversations.on_thread(HOME.id, thread))
    assert found is not None
    return found


def test_a_reply_after_opening_and_moving_to_a_bench_is_said_in_its_talk_after_the_carried_ask(
        wired: Fakes, shop: Shop) -> None:
    wired.inference.script = [open_bench(), move(), REPLY]
    asyncio.run(respond(CHAT))
    chat, talk = turn_in(wired, "person:1:web"), turn_in(wired, "bench:9")
    asked = chat.turns[0]
    assert [(t.author, t.text, t.carried_from) for t in talk.turns[:1]] == [("person", CHAT.text, asked.id)]
    assert (talk.turns[1].author, talk.turns[1].text, talk.turns[1].answers) == ("ashley", REPLY.text, talk.turns[0].id)
    assert len(talk.turns) == 2


def test_chat_keeps_the_ask_and_continues_on_the_bench_instead_of_her_reply(wired: Fakes, shop: Shop) -> None:
    wired.inference.script = [open_bench(), move(), REPLY]
    asyncio.run(respond(CHAT))
    chat = turn_in(wired, "person:1:web")
    assert [t.author for t in chat.turns] == ["person", "ashley"]
    assert chat.turns[0].text == CHAT.text
    assert chat.turns[1].continued_on == 9 and chat.turns[1].answers == chat.turns[0].id
    assert REPLY.text not in chat.turns[1].text and "Alana comes home" in chat.turns[1].text


def test_after_the_move_she_has_the_benchs_tools_and_leads_on_a_bench_she_just_opened(wired: Fakes, shop: Shop) -> None:
    wired.inference.script = [open_bench(), move(), add_piece(), REPLY]
    asyncio.run(respond(CHAT))
    before, after = ([s.name for s in p.tools] for p in (wired.inference.prompts[0], wired.inference.prompts[2]))
    assert "bench_add" not in before and "bench_add" in after
    assert shop.applied and shop.applied[0][1] == 9
    assert lead(bench_tools.CONFIG.lead_adds) not in wired.inference.prompts[0].system["default"].moment
    assert lead(bench_tools.CONFIG.lead_adds) in wired.inference.prompts[2].system["default"].moment


def test_a_bench_that_was_already_open_is_moved_to_without_the_lead(wired: Fakes, shop: Shop) -> None:
    wired.inference.script = [move(), REPLY]
    asyncio.run(respond(CHAT))
    assert lead(bench_tools.CONFIG.lead_adds) not in wired.inference.prompts[1].system["default"].moment
    assert "bench_add" in [s.name for s in wired.inference.prompts[1].tools]
    assert turn_in(wired, "bench:9").turns[-1].text == REPLY.text


@pytest.mark.parametrize("to", ["chat", "memory", "devices", "workshop"])
def test_a_move_to_anything_but_a_bench_leaves_her_reply_in_chat(wired: Fakes, shop: Shop, to: str) -> None:
    wired.inference.script = [ToolCalls((ToolCall("m", "move_page", {"to": to}),)), REPLY]
    asyncio.run(respond(CHAT))
    assert [t.text for t in turn_in(wired, "person:1:web").turns][-1] == REPLY.text
    assert asyncio.run(wired.conversations.on_thread(HOME.id, "bench:9")) is None


def test_moving_to_a_bench_and_back_to_chat_keeps_her_reply_in_chat(wired: Fakes, shop: Shop) -> None:
    wired.inference.script = [move(), ToolCalls((ToolCall("m2", "move_page", {"to": "chat"}),)), REPLY]
    asyncio.run(respond(CHAT))
    assert turn_in(wired, "person:1:web").turns[-1].text == REPLY.text


def test_a_bench_talk_that_moves_to_its_own_bench_stays_there(wired: Fakes, shop: Shop) -> None:
    wired.inference.script = [move(), REPLY]
    asyncio.run(respond(BENCH_TALK))
    talk = turn_in(wired, "bench:9")
    assert [t.author for t in talk.turns] == ["person", "ashley"] and talk.turns[1].continued_on is None


def test_a_move_to_a_bench_that_is_not_theirs_moves_nothing_and_she_answers_in_chat(wired: Fakes, shop: Shop) -> None:
    shop.mine = ()
    wired.inference.script = [move(), REPLY]
    asyncio.run(respond(CHAT))
    assert turn_in(wired, "person:1:web").turns[-1].text == REPLY.text
    assert asyncio.run(wired.conversations.on_thread(HOME.id, "bench:9")) is None


def test_a_bench_that_cannot_be_read_leaves_her_reply_in_chat(wired: Fakes, shop: Shop) -> None:
    shop.down = True
    wired.inference.script = [move(), REPLY]
    asyncio.run(respond(CHAT))
    assert turn_in(wired, "person:1:web").turns[-1].text == REPLY.text


def test_a_checkpoint_keeps_where_the_page_moved_to_so_a_resumed_turn_is_already_there(shop: Shop) -> None:
    from ashley.channels.checkpoint import Checkpoint, dumps, loads
    from ashley.channels.landing import Landing
    from ashley.channels.respond import LIMITS
    from ashley.channels.tool_loop import Progress
    from ashley.inference.model import SystemPrompt

    moved = replace(CHAT, moved_to=9)
    saved = loads(dumps(Checkpoint(moved, 1, 2, ALANA.id, {"default": SystemPrompt("s", "m")}, Progress((), 0, 0))))
    assert saved.inbound.moved_to == 9
    names = [s.name for s in asyncio.run(Landing(saved.inbound, (1, 2), LIMITS).catalogue()).specs]
    assert "bench_add" in names


def test_a_turn_that_moved_to_a_bench_has_the_benchs_room_to_work_not_chats(wired: Fakes, shop: Shop) -> None:
    from ashley.channels.respond import LIMITS

    rounds = LIMITS["chat"].max_tool_rounds + 4
    assert LIMITS["brainstorm"].max_tool_rounds > rounds
    reads = [ToolCalls((ToolCall(f"r{i}", "bench_read", {"i": i}),)) for i in range(rounds)]
    wired.inference.script = [move(), *reads, REPLY]
    asyncio.run(respond(CHAT))
    assert {p.tool_choice for p in wired.inference.prompts} == {"auto"}
    assert turn_in(wired, "bench:9").turns[-1].text == REPLY.text


def test_the_steps_after_the_move_run_as_the_benchs_talk_and_so_does_the_answer_a_held_line_stood_for(
        wired: Fakes, shop: Shop) -> None:
    from later_support import until

    held = Reply(answers=False, spoken="One moment.", text="One moment.")
    wired.inference.script = [open_bench(), move(), held, add_piece(), REPLY]

    async def scenario() -> None:
        out = await respond(replace(CHAT, later=True))
        assert out.follows
        await until(lambda: shop.applied)
        await until(lambda: "bench:9" in wired.conversations.threads
                     and len(wired.conversations.convs[wired.conversations.threads["bench:9"]].turns) == 3)

    asyncio.run(scenario())
    assert wired.inference.tasks == ["chat", "chat", "brainstorm", "brainstorm", "brainstorm"]
    after = wired.inference.prompts[3]
    assert "bench_add" in [s.name for s in after.tools]
    assert lead(bench_tools.CONFIG.lead_adds) in after.system["default"].moment


def test_the_landing_is_saved_by_the_move_itself_before_its_result_is_returned(wired: Fakes, shop: Shop) -> None:
    from ashley.channels.landing import Landing
    from ashley.channels.respond import LIMITS
    from ashley.channels.tool_loop import Steps

    class Saves(Steps):
        def __init__(self) -> None:
            self.saved: list[int | None] = []

        async def arrived(self, inbound: Inbound) -> None:
            self.saved.append(inbound.moved_to)

    saves = Saves()
    landing = Landing(CHAT, (1, 2), LIMITS)
    landing.recording(saves)
    asyncio.run(landing.call(ToolCall("m", "move_page", {"to": "bench", "bench_id": 9})))
    assert saves.saved == [9] and landing.inbound.moved_to == 9


def test_a_pod_that_resumes_a_turn_whose_page_had_moved_offers_the_bench_from_its_first_step(
        wired: Fakes, shop: Shop) -> None:
    from ashley.channels.landing import Landing
    from ashley.channels.respond import LIMITS
    from ashley.channels.tool_loop import Progress, resumed
    from ashley.inference.model import SystemPrompt

    moved = replace(CHAT, moved_to=9)
    landing = Landing(moved, (1, 2), LIMITS)
    system = {"default": SystemPrompt("stable", "moment")}
    wired.inference.script = [REPLY]
    asyncio.run(resumed(Progress((Message("person", "hi"),), 0, 0), "chat", system, (), LIMITS["chat"], 1, landing,
                        False, 0.0, arrive=landing.arrived))
    (first,) = wired.inference.prompts
    assert "bench_add" in [s.name for s in first.tools]
    assert wired.inference.tasks == ["brainstorm"]
    assert "bench" in first.system["default"].moment and first.system["default"].moment != "moment"


def _held(text: str = "One moment.") -> Reply:
    return Reply(answers=False, spoken=text, text=text)


def _texts(wired: Fakes, thread: str) -> list[tuple[str, str, bool]]:
    return [(t.author, t.text, t.follows) for t in turn_in(wired, thread).turns]


def _run_held(wired: Fakes, script: list[ToolCalls | Reply]) -> None:
    from later_support import until

    wired.inference.script = list(script)

    async def scenario() -> None:
        out = await respond(CHAT)
        assert out.follows
        await until(lambda: not wired.inference.script)
        await until(lambda: any(t.continued_on == 9 for c in wired.conversations.convs.values() for t in c.turns))

    asyncio.run(scenario())


def test_a_held_line_said_after_the_page_moved_is_said_in_the_bench_talk_after_the_carried_ask(
        wired: Fakes, shop: Shop) -> None:
    _run_held(wired, [open_bench(), move(), _held(), add_piece(), REPLY])
    assert _texts(wired, "bench:9") == [("person", CHAT.text, False), ("ashley", "One moment.", True),
                                        ("ashley", REPLY.text, False)]
    assert [t.author for t in turn_in(wired, "person:1:web").turns] == ["person", "ashley"]
    talk = turn_in(wired, "bench:9").turns
    assert talk[1].answers == talk[0].id and talk[0].carried_from == turn_in(wired, "person:1:web").turns[0].id


def test_a_held_line_said_before_the_move_stays_in_chat_and_the_answer_lands_on_the_bench(
        wired: Fakes, shop: Shop) -> None:
    _run_held(wired, [_held(), open_bench(), move(), add_piece(), REPLY])
    assert _texts(wired, "person:1:web")[:2] == [("person", CHAT.text, False), ("ashley", "One moment.", True)]
    assert _texts(wired, "bench:9") == [("person", CHAT.text, False), ("ashley", REPLY.text, False)]


def test_the_ask_is_in_the_bench_talk_before_the_first_step_after_the_move(wired: Fakes, shop: Shop) -> None:
    seen: list[int] = []

    class Watching(FakeInference):
        async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                       conversation_id: int | None = None) -> T | ToolCalls:
            found = await wired.conversations.on_thread(HOME.id, "bench:9")
            seen.append(0 if found is None else len(found.turns))
            return await super().step(task, prompt, output, conversation_id=conversation_id)

    watching = Watching(script=[move(), add_piece(), REPLY])
    services.register(Inference, watching)
    asyncio.run(respond(CHAT))
    assert seen[:3] == [0, 1, 1]


def _thinking_told(wired: Fakes, monkeypatch: pytest.MonkeyPatch, at_most_s: float, per_step_s: float) -> int:
    """How often the screens are told she is thinking in a four-step turn whose steps take `per_step_s` each."""
    from ashley.channels import live_turn
    from ashley.live.events import HerState

    now = [100.0]

    class Slow(FakeInference):
        async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                       conversation_id: int | None = None) -> T | ToolCalls:
            got = await super().step(task, prompt, output, conversation_id=conversation_id)
            now[0] += per_step_s
            return got

    monkeypatch.setattr(live_turn, "AT_MOST_S", at_most_s)
    monkeypatch.setattr(live_turn.time, "monotonic", lambda: now[0])
    live = FakeLive()
    services.register(Live, live)
    services.register(Inference, Slow(script=[move(), add_piece(), add_piece(), REPLY]))
    asyncio.run(respond(CHAT))
    return [e.state for e in live.published if isinstance(e, HerState)].count("thinking")


def test_thinking_is_told_again_once_half_of_what_a_screen_believes_has_passed(
        wired: Fakes, shop: Shop, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _thinking_told(wired, monkeypatch, at_most_s=10.0, per_step_s=6.0) == 4


def test_thinking_is_not_told_again_before_half_of_what_a_screen_believes_has_passed(
        wired: Fakes, shop: Shop, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _thinking_told(wired, monkeypatch, at_most_s=10.0, per_step_s=1.0) == 1


class _Kept(Work):
    """Work that outlives its runner and has not yet told the person her thinking is out of reach."""

    def __init__(self) -> None:
        self.told = False

    @property
    def retries(self) -> bool:
        return True

    @property
    def unreachable_told(self) -> bool:
        return self.told

    async def told_unreachable(self) -> None:
        self.told = True


def _unreachable(wired: Fakes, moved_to: int | None) -> tuple[Showing, _Kept, int, int]:
    """A device-spoken turn (a channel that is not a page) in chat whose page is on `moved_to`, ended on an
    unreachable model."""
    async def scenario() -> tuple[Showing, _Kept, int, int]:
        inbound = replace(CHAT, medium="spoken", audience="shared", shared=True, device_id=4, moved_to=moved_to)
        chat = await wired.conversations.for_thread(HOME.id, inbound.thread, "chat", [ALANA.id])
        said = await wired.conversations.add_turn(chat.id, NewTurn("person", inbound.text, ALANA.id, "shared", None))
        showing, work = Showing(inbound, "t"), _Kept()
        ended = Ended(inbound, chat.id, said.id, ALANA, showing)
        assert await settle(work, InferenceUnavailable(), "inference_unavailable", ended, 1.0)
        assert work.told
        return showing, work, chat.id, said.id

    return asyncio.run(scenario())


def test_the_unreachable_line_of_a_turn_moved_to_a_bench_is_said_in_the_bench_talk_not_where_it_began(
        wired: Fakes, shop: Shop) -> None:
    _unreachable(wired, 9)
    chat, talk = turn_in(wired, "person:1:web"), turn_in(wired, "bench:9")
    assert [t.author for t in chat.turns] == ["person"]
    assert [(t.author, t.follows, t.carried_from) for t in talk.turns] == [("person", False, chat.turns[0].id),
                                                                             ("ashley", True, None)]
    assert talk.turns[1].text == unreachable().text and talk.turns[1].answers == talk.turns[0].id


def test_the_unreachable_line_of_a_turn_that_did_not_move_is_said_where_it_began(wired: Fakes, shop: Shop) -> None:
    _unreachable(wired, None)
    chat = turn_in(wired, "person:1:web")
    assert [(t.author, t.follows, t.answers) for t in chat.turns] == [("person", False, None),
                                                                     ("ashley", True, chat.turns[0].id)]
    assert "bench:9" not in wired.conversations.threads


def test_the_screen_is_told_of_the_bench_talk_when_the_unreachable_line_is_said_there(wired: Fakes, shop: Shop) -> None:
    _unreachable(wired, 9)
    live = services.get(Live)
    assert isinstance(live, FakeLive)
    told = [e.thread for e in live.published if isinstance(e, ThreadTurn)]
    assert told[-1] == "bench:9" and "person:1:web" not in told[-1:]
