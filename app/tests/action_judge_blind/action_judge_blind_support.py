"""Helpers for the blind tests of the action judge (`~/scratch/ashley/readers-design/design.txt`, sections 3, 4, P3, and
the owner decisions). The judge is exercised at the provider boundary: the real `RoutedInference` over a fake provider
that records the exact request and plays scripted verdicts, the real model-backed judge behind `Outside`, the real mail,
house and bench tools, the real proposals and `outside_actions` stores.

Every guess about a name P3 adds is in ASSUMPTIONS below and only here, so the reconciler rewires one file."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, fields, replace
from typing import Any

import httpx2
from ashley import services
from ashley.channels import judge_words, standing
from ashley.channels.model import Inbound
from ashley.channels.steps import NO_STEPS, Steps
from ashley.conversations.conversations import Conversations
from ashley.tools import outside_config
from ashley.conversations.postgres import PostgresConversations
from ashley.inference.inference import Inference
from ashley.conversations.inflight import Claim, NullInFlight
from ashley.inference.model import Entry, SystemPrompt, ToolCall, ToolChoice, ToolResult, ToolSpec
from ashley.inference.provider import Completion, ToolUse
from pydantic import BaseModel
from ashley.mail.mailbox import Mailbox
from ashley.connections.model import Resource
from ashley.connections.resources import ConnectionResources, Use
from ashley.senses.proposal_payloads import OUTSIDE, HeldCall
from ashley.tools.action_judge import ActionJudge
from ashley.tools.action_judge_model import ModelActionJudge
from ashley.tools.mail import MailTools
from ashley.tools.outside import Outside
from ashley.tools.tools import Tools
from contract.conversations_support import POLICY, run as run_bounded, scalar
from contract.inference_support import Asked, Clock, FakeLedger, FakeProvider, Step, fail, refuse, route, router, table
from mail_gmail_support import ALANA, FakeGmail, HOME, HeldResources, connect, message, wire
from taint_tiers_blind.taint_tiers_blind_support import PLANT, Source, Tiered, World, spec, tiered

# --- ASSUMPTIONS: every guess, change here only ----------------------------------------------------------------------
# G1  The model-backed judge is `ashley.tools.action_judge.ModelJudge()` (no arguments; asks the registered `Inference`
#     for the task `action_judge`), registered as the `ActionJudge` service. The Null Object is already on the base.
# G2  The judge's structured output has the fields `decision`, `reason`, `explanation` (design 3.2); the scripted
#     provider answers a dict of exactly those. The task name `action_judge` is listed in `routes.TASKS`, so the shared
#     `table(...)` helper routes it to the fake provider.
# G3  WORDS are read from the conversation store: this speaker's `author = 'person'` turns of the conversation, up to and
#     including the turn being answered (`Outside`'s `turn`), through the registered `Conversations` (or the same rows).
#     Her turns (`author = 'ashley'`) are never WORDS. The current message is stored before the call, as on main.
# G4  `HeldCall` gains `explanation: str` (design 3.3: "stored in the HeldCall beside the code-written summary").
# G5  A mail recipient that fails the code check (4.3) is held with the reason `recipient_unknown` (the owner's
#     decision: the enum value, not design 4.3's `data_leaves_household`). Where it is logged is not pinned: any log
#     record's fields carry `reason` equal to it. The judge is not called.
# G6  A household person's address is the ref of a mailbox the household's connections reach
#     (`ConnectionResources.of_household`): the repo stores no email account on a person.
# G7  The sent-to check is one provider query on the mailbox: a `messages` list with `q` containing `in:sent` and
#     `to:<address>`; a non-empty answer means the address was sent to before.
# G8  A watch- or reminder-woken turn's WORDS come from the creating turn's person messages. The fired turn is built
#     with the real `reminder_turn.inbound`; how `Outside` learns the creating turn from it is not pinned: `inherited`
#     below is the one place that wires it (here: the same `World.wrap` the tier suite uses, with the inbound given).
# G9  The verdict is checkpointed through the turn's `Steps` (a real `Saved`); a resumed turn is a new `Outside` over a
#     `Saved` rebuilt from the saved checkpoint JSON, asked for the same call id.
# G10 `outside_actions` rows of a judged `run` have `tier == "judged"`, `reason`, `explanation`; the "done" block under her
#     reply (`Outside.done_block`) lists the explanation.
# G11 The run record, the done block and the held result all carry the judge's explanation text verbatim.
# ---------------------------------------------------------------------------------------------------------------------

UNKNOWN_RECIPIENT = {"recipient_unknown"}
EXPLANATION = "EXPL-you-asked-for-this-3c1d"
WORDS = "please email Pat the signed form"
KNOWN = "pat@school.test"
STRANGER = "mallory@evil.test"
SAM_ADDRESS = "sam@moore.test"
SENT_BEFORE = "coach@club.test"
FORM = {"to": [KNOWN], "subject": "Form", "body": "It is signed."}


def says(decision: str, reason: str = "asked_directly", explanation: str = EXPLANATION) -> Step:
    return Step({"decision": decision, "reason": reason, "explanation": explanation})


class TimingOut(FakeProvider):
    """A provider whose call times out, as a real one does when its request deadline passes."""

    async def complete[T: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...],
                                      tool_choice: ToolChoice, output: type[T],
                                      timeout_s: float) -> Completion[T] | ToolUse:
        self.asked.append(Asked(model, params, system, messages, output, timeout_s, tools, tool_choice))
        raise TimeoutError("slow")


FAULTS: dict[str, Step | None] = {
    "unavailable": fail("unavailable"), "invalid_output": fail("invalid_output"), "error": fail("error"),
    "refused": refuse(), "unknown_decision": Step({"decision": "maybe", "reason": "unclear", "explanation": "x"}),
    "unknown_reason": Step({"decision": "run", "reason": "because", "explanation": "x"}),
    "wrong_shape": Step({"answer": "run"}), "timeout": None}


class Housemates(HeldResources):
    """The held mailboxes, and Sam's, a mailbox of the household that connection resources list beside Alana's."""

    async def of_household(self, household_id: int, person_id: int | None = None) -> dict[int, tuple[Resource, ...]]:
        return {**await super().of_household(household_id, person_id),
                99: (Resource(SAM_ADDRESS, "mailbox", SAM_ADDRESS, True),)}


class SentGmail(FakeGmail):
    """A fake Gmail that has sent to `sent_to` before: a list query for `in:sent to:<address>` finds a sent message
    whose To header is that address, and reading it answers as Gmail does."""

    def __init__(self, sent_to: Iterable[str] = ()) -> None:
        super().__init__([message("a1", "Field trip", 1_762_000_000_000, ("INBOX",))])
        self.sent = {f"old-{i}": a for i, a in enumerate(sent_to)}

    def sent_queries(self) -> list[str]:
        return [q for p, query, _ in self.seen if p == "/messages" for q in query.get("q", [])
                if "sent" in q.lower() and "to:" in q.lower()]

    def _old(self, id_: str) -> dict[str, Any]:
        found = message(id_, "Sent before", 1_761_000_000_000, ("SENT",))
        headers = [{**h, "value": self.sent[id_]} if h["name"] == "To" else h for h in found["payload"]["headers"]]
        return {**found, "payload": {**found["payload"], "headers": headers}}

    def _route(self, path: str, query: dict[str, list[str]]) -> Any:
        q = " ".join(query.get("q", [])).lower()
        if path == "/messages" and "to:" in q and "sent" in q:
            hits = [i for i, a in self.sent.items() if a.lower() in q]
            return httpx2.Response(200, json={"resultSizeEstimate": len(hits), **(
                {"messages": [{"id": i, "threadId": "t" + i} for i in hits]} if hits else {})})
        if path.removeprefix("/messages/") in self.sent:
            return httpx2.Response(200, json=self._old(path.removeprefix("/messages/")))
        return super()._route(path, query)


class RealWords(World):
    """The tiered suite's world, wrapping `Outside` with the words the shipped `channels.judge_words` reads for the
    turn's conversation, in place of the fixed words the tiered suite gives it."""

    def wrap(self, source: Tools, inbound: Inbound | None = None, turn: int | None = None, conv: int | None = None,
             steps: Steps = NO_STEPS, tainted: str | None = None) -> Outside:
        got = inbound or self.inbound()
        config = outside_config.load()
        chat = conv or self.chat
        words = judge_words.reader(got, chat, config.words_turns, config.words_chars)
        outside = Outside(source, standing.of(got), (chat, turn or self.turn()), steps, tainted or got.taint,
                               words=words)
        if steps is not NO_STEPS:
            outside.judging(steps)
        return outside


@dataclass
class Judged:
    """A tiered world with the real model-backed judge over a scripted provider."""

    t: Tiered
    provider: FakeProvider

    @property
    def w(self) -> World:
        return self.t.w

    def say(self, text: str, author: str = "person") -> int:
        speaker = self.w.alana if author == "person" else None
        return int(scalar(self.w.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                          "visibility) VALUES (%s, %s, %s, %s, %s, 'shared') RETURNING id",
                          (self.w.chat, self.w.hid, author, speaker, text)))

    def outside(self, inner: Any, words: str = WORDS, tainted: str | None = "look_up",
                earlier: Sequence[tuple[str, str]] = ()) -> Outside:
        """`Outside` over `inner` for Alana's turn saying `words`, after `earlier` (author, text) turns, tainted."""
        for author, text in earlier:
            self.say(text, author)
        turn = self.say(words)
        inbound = replace(self.w.inbound(), text=words)
        return self.w.wrap(inner, inbound, turn=turn, tainted=tainted)

    def request(self) -> str:
        """Everything the provider was sent, system and messages, as one string."""
        return repr(self.provider.asked)

    @property
    def calls(self) -> int:
        return len(self.provider.asked)

    async def held(self) -> list[HeldCall]:
        found = await self.w.store.pending(self.w.alana, self.w.chat, OUTSIDE)
        return [] if found is None else list(found.payload.calls)


def mail(sent_to: Iterable[str] = ()) -> tuple[MailTools, SentGmail]:
    gmail = SentGmail(sent_to)
    wire(gmail)
    held = connect()
    services.register(ConnectionResources, Housemates(held))
    return MailTools(Use(HOME, ALANA, True), 8000), gmail


def sends(gmail: FakeGmail) -> list[str]:
    return [p for p, _ in gmail.posted if p == "/messages/send"]


@asynccontextmanager
async def judging(url: str, script: Iterable[Step] = (), provider: FakeProvider | None = None) -> AsyncGenerator[Judged]:
    async with tiered(url) as t:
        t.w = RealWords(**{f.name: getattr(t.w, f.name) for f in fields(t.w)})
        served = provider or FakeProvider("alpha", list(script) or [says("ask", "unclear")], Clock())
        wired: dict[Any, Any] = {
            Inference: router(table([route("alpha")]), [served], FakeLedger()),
            Conversations: PostgresConversations(t.w.db, POLICY),
            ActionJudge: ModelActionJudge()}
        for interface, provider_ in wired.items():
            services.register(interface, provider_)
        try:
            yield Judged(t, served)
        finally:
            for interface in wired:
                services.unregister(interface)
            services.unregister(Mailbox)
            services.unregister(ConnectionResources)


def fields_of(records: Iterable[Any]) -> str:
    """Every log record's whole state, its structured fields included (`caplog.text` omits them)."""
    return repr([r.__dict__ for r in records])


def judged_events(records: Iterable[Any], event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in records if r.getMessage() == event]


def free_text_source() -> Source:
    """A source offering a read that answers outside text, and a change of an unknown name whose arguments are text."""
    src = Source((spec("web_read", True, True), ToolSpec("claude_prompt", "claude_prompt", {
        "type": "object", "properties": {"session": {"type": "string"}, "prompt": {"type": "string"}}}, outside=False)))
    src.answers["web_read"] = (f"the page says {PLANT}", True)
    return src


def prompt_call(text: str = "x") -> ToolCall:
    return ToolCall("p1", "claude_prompt", {"session": "s-9", "prompt": text})



def run_judged(url: str, body: Callable[[Judged], Awaitable[None]], script: Iterable[Step] = (),
               provider: FakeProvider | None = None) -> None:
    """`body` over a `Judged` world whose provider plays `script` (default: one `ask`), bounded."""
    async def inside() -> None:
        async with judging(url, script, provider) as j:
            await body(j)

    run_bounded(inside(), 40.0)


class Keeping(NullInFlight):
    """An `InFlight` that keeps each saved checkpoint text."""

    def __init__(self) -> None:
        self.saved: list[str] = []

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        self.saved.append(checkpoint)
        return Claim(said_id, conversation_id, "h")

    async def save(self, claim: Claim, checkpoint: str) -> None:
        self.saved.append(checkpoint)


class Crashing(Source):
    """A source whose first call to `tool` dies as a killed pod does, before answering."""

    def __init__(self, specs: tuple[ToolSpec, ...], tool: str) -> None:
        super().__init__(specs)
        self.tool, self.crashed = tool, False

    async def call(self, call: ToolCall) -> ToolResult:
        if call.name == self.tool and not self.crashed:
            self.crashed = True
            raise RuntimeError("pod killed")
        return await super().call(call)
