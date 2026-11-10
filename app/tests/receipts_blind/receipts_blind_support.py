"""Support for the blind tests of "receipts leave her words" (`~/scratch/ashley/receipts/spec.txt`, its numbered contract
and the orchestrator override): the real turn loop over a real database with the real proposals store, outside record,
outbox and in-flight store, a scripted model, tools that record each call, and a judge that answers per tool.

Every guess about a name the change adds is in the G-list below and only here, so a reconciler rewires this one file.
Everything else is existing code on main.

G1  `Receipt`, `Receipts` and `NewTurn.receipts`/`Turn.receipts` are in `ashley.conversations.model`; `Outbound.receipts`
    is in `ashley.channels.model` (the spec's INTERFACES).
G2  `ToolSpec.label` is a keyword; `Outside.receipts()` and `Landing.receipts` (set by `Landing.closing`) are as the spec
    says. A headline for a tool with no label is `outside_config.load().unlabelled`.
G3  The configured strings are attributes of the loaded configs: `outside_config.load().unlabelled` and `.history_line`
    (a template; its text before the first `{` is its fixed part), the Discord config's `held_footer`, the push config's
    `done_title` and `held_title`.
G4  `receipt_lines` is a function of the package `ashley.channels.discord`, `receipt_lines(receipts, config)`.
G5  The wire carries `receipts` as `{"done": [{"headline", "detail", "why"}], "held": [...], "proposal_id": n}` or null,
    on `ChatConversationTurn`, `ChatReply` and `MessageResponse`; read here as JSON, never through a model class.
G6  `Outbound.receipts` survives the outbox: `Later.outbound.receipts` equals what was queued.
G7  A receipt-only push is an `Outbound` of body "" on the thread `push:<speaker id>` carrying `receipts`.
G8  `receipts.unshown` and `outside.receipts` are log events with the fields the spec names.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Generator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Later, Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.respond import respond
from ashley.channels.push import config as push_config
from ashley.channels.push.later import push
from ashley.channels.push.sender import Notification
from ashley.channels.push.subscriptions import Subscription, Subscriptions
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind, Receipt, Receipts, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.postgres_outside_record import PostgresOutsideRecord
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.presence import Presence
from ashley.senses.proposals import Proposals
from ashley.signin.model import SignedIn
from ashley.tools import outside_config
from ashley.tools.action_judge import ActionJudge, Decision, Verdict, View
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, scalar
from push_support import FakeSender, FakeSubscriptions, browser

LAMP_LABEL = "RB-LABEL-lamp-9c2e"
MAIL_LABEL = "RB-LABEL-mail-4d71"
CHIME_LABEL = "RB-LABEL-chime-b38a"
ROOM_PLANT = "RB-ROOM-porch-e51f"
WHY_RAN = "RB-WHY-ran-7a90"
WHY_ASKED = "RB-WHY-asked-2c6d"
OLD_DONE_INTRO = "Done after reading outside text:"
OLD_HELD_INTRO = "Waiting for your OK, not done yet:"
OKAY = "Okay."

LOOK = ToolSpec("look", "look something up", {"type": "object"}, reads=True, outside=True)
LAMP = ToolSpec("house_do", "do a thing in the house", {"type": "object"}, label=LAMP_LABEL)
MAIL = ToolSpec("mail_label", "file a mail", {"type": "object"}, label=MAIL_LABEL)
CHIME = ToolSpec("chime", "ring a chime", {"type": "object"}, tier="runs", label=CHIME_LABEL)
MYSTERY = ToolSpec("mystery_change", "a change nobody labelled", {"type": "object"})
SPECS = (LOOK, LAMP, MAIL, CHIME, MYSTERY)

CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
ANSWER = Reply(spoken=OKAY, text=OKAY)
CLAIM_S = 0.3


def looked() -> ToolCalls:
    return ToolCalls((ToolCall("l1", LOOK.name, {}),))


def change(name: str = "house_do", call_id: str = "c1", **arguments: object) -> ToolCalls:
    args: dict[str, object] = {"action": "light.turn_on", "room": ROOM_PLANT} if not arguments else dict(arguments)
    return ToolCalls((ToolCall(call_id, name, args),))


def changes(*names: str) -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"c{i}", n, {"action": "light.turn_on", "room": f"{ROOM_PLANT}-{i}"})
                           for i, n in enumerate(names, 1)))


class Hang(Exception):
    """A step scripted as `HANG` waits until its runner is killed."""


HANG = Hang()


@dataclass
class Model(Inference):
    script: list[ToolCalls | Reply | Hang] = field(default_factory=list[ToolCalls | Reply | Hang])
    asked: asyncio.Event = field(default_factory=asyncio.Event)
    prompts: list[Prompt] = field(default_factory=list[Prompt])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        self.prompts.append(prompt)
        got = self.script.pop(0)
        if isinstance(got, Hang):
            self.asked.set()
            await asyncio.Event().wait()
        assert not isinstance(got, Hang)
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")


@dataclass
class Switchboard(Tools):
    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue(SPECS, "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, '{"ok": true}')


class Judge(ActionJudge):
    """Answers `run` unless the tool is in `answers`."""

    def __init__(self, answers: Mapping[str, Decision] | None = None) -> None:
        self.answers: dict[str, Decision] = dict(answers or {})
        self.asked: list[str] = []

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked.append(view.tool)
        if self.answers.get(view.tool, "run") == "run":
            return Verdict("run", "asked_directly", WHY_RAN)
        return Verdict("ask", "not_asked", WHY_ASKED)


@dataclass
class OnePerson(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class Nobody(Presence):
    async def home(self, household_id: int) -> frozenset[int] | None:
        return None


@dataclass
class Pod:
    model: Model
    tools: Switchboard


@dataclass
class Played:
    """What a played turn left: the reply as returned, the conversation, her stored turns oldest first, and every reply the
    outbox then held."""

    out: Outbound
    conversation_id: int
    turns: list[Turn]
    queued: list[Later]

    @property
    def answer(self) -> Turn:
        """Her final answer: the last turn of hers that does not merely follow."""
        return [t for t in self.turns if not t.follows][-1]


@dataclass
class World:
    url: str
    who: Person
    first: Pod
    second: Pod
    judge: Judge
    subscriptions: FakeSubscriptions

    def web(self, text: str = "turn on the lamp") -> Inbound:
        return inbound_from(SignedIn(1, self.who), ChatRequest(text=text))

    def discord(self, text: str = "turn on the lamp", shared: bool = False) -> Inbound:
        return Inbound(household_id=self.who.household_id, thread="discord:1001", text=text, kind="chat", medium="text",
                       audience="household" if shared else "owner", speaker_id=self.who.id, shared=shared, place=None,
                       channel="discord", later=True, later_by="outbox")

    def voice(self, text: str = "turn on the lamp") -> Inbound:
        return Inbound(household_id=self.who.household_id, thread="device:3", text=text, kind="command", medium="spoken",
                       audience="owner", speaker_id=self.who.id, shared=False, place="den", channel="device")

    def phone(self) -> None:
        """The speaker has a browser subscribed, so a spoken turn can reach their phone."""
        self.subscriptions.rows.append(Subscription(1, self.who.household_id, self.who.id, browser(1)))

    def as_pod(self, pod: Pod) -> None:
        services.register(Inference, pod.model)
        services.register(Tools, pod.tools)

    def count(self, query: str) -> int:
        return int(scalar(self.url, query))


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    made = World(db_url, who, Pod(Model(), Switchboard()), Pod(Model(), Switchboard()), Judge(), FakeSubscriptions())
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    services.register(ActionJudge, made.judge)
    services.register(Subscriptions, made.subscriptions)
    yield made
    for interface in (People, Presence, Inference, Tools, ActionJudge, Subscriptions):
        services.unregister(interface)


@asynccontextmanager
async def database(world: World) -> AsyncGenerator[PoolDatabase]:
    """The real stores on the test's database, registered for the turn loop."""
    db = PoolDatabase(world.url, connect_timeout_s=5.0)
    await db.open()
    keep_actions, keep_writes = outside_config.keeps()
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, claim_s=CLAIM_S))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Proposals, PostgresProposals(db))
    services.register(OutsideRecord, PostgresOutsideRecord(db, keep_actions, keep_writes))
    try:
        yield db
    finally:
        for interface in (Conversations, InFlight, Outbox, Proposals, OutsideRecord):
            services.unregister(interface)
        await db.close()


async def hers(conversation_id: int) -> list[Turn]:
    found = await services.get(Conversations).get(conversation_id)
    assert found is not None
    return [t for t in found.turns if t.author == "ashley"]


async def settled(conversation_id: int, count: int, timeout: float = 5.0) -> list[Turn]:
    """Wait for her `count`th turn to be stored; her turns."""
    async with asyncio.timeout(timeout):
        while len(await hers(conversation_id)) < count:
            await asyncio.sleep(0.02)
    return await hers(conversation_id)


async def queued() -> list[Later]:
    """Every reply the outbox holds, taken."""
    box = services.get(Outbox)
    return [row for prefix in ("push:", "discord:", "device:", "person:") for row in await box.take(prefix)]


async def play(world: World, inbound: Inbound, script: Sequence[ToolCalls | Reply | Hang]) -> Played:
    """One person turn through `respond` on the first pod, to her final answer stored and the outbox taken."""
    world.as_pod(world.first)
    world.first.model.script = list(script)
    out = await respond(inbound)
    conversation = out.conversation_id
    turns = await settled(conversation, 2 if inbound.later else 1)
    return Played(out, conversation, turns, await queued())


def snapshot(turn: Turn) -> Receipts | None:
    return turn.receipts


def fixed_part(template: str) -> str:
    """The text of a template before its first placeholder."""
    return template.split("{")[0].strip()


def receipt_strings(receipts: Receipts | None) -> list[str]:
    """Every string code writes about a change: the configured ones that belong to receipts and, when `receipts` is given,
    each of its headlines, details and whys. A reply's words hold none."""
    config = outside_config.load()
    fixed = [OLD_DONE_INTRO, OLD_HELD_INTRO, config.unlabelled, fixed_part(config.history_line)]
    if receipts is not None:
        for r in (*receipts.done, *receipts.held):
            fixed += [s for s in (r.headline, r.detail, r.why) if s]
    assert all(fixed), "an empty receipt string would be found in any text"
    return fixed


def _wire(r: Receipt) -> dict[str, str | None]:
    return {"headline": r.headline, "detail": r.detail, "why": r.why}


WIRE_RAN = "ran"
"""The wire's name for the changes that ran: the API contract refuses one field name with two types, and a bool `done`
exists elsewhere."""


def json_receipts(receipts: Receipts | None) -> dict[str, Any] | None:
    """`receipts` as the wire states it (G5)."""
    if receipts is None:
        return None
    return {WIRE_RAN: [_wire(r) for r in receipts.done], "held": [_wire(r) for r in receipts.held],
            "proposal_id": receipts.proposal_id}


def same_json(a: object, b: object) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


async def notified(row: Later) -> list[Notification]:
    """The notifications the push singleton sends the person's browsers for one queued reply."""
    sender = FakeSender()
    await push(sender, push_config.load(), row)
    return [n for _, n in sender.sends]
