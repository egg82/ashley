"""Helpers for the blind contract tests of part 2 of "What she could not do for want of a source" (`decisions.md`):
`Reply.owed`, what `respond` keeps of it, `Errands.owe`, `Errands.untold` and `Errands.told`, the `# While they were
away` section of the prompt, and the `owed`, `owed_dropped` and `told` fields of `respond.done`.

Every guess beyond the design is in the ASSUMPTIONS section and only there; they are listed one per line in
`~/scratch/ashley/errands/owed-blind/assumptions.txt`."""

import asyncio
from collections.abc import Collection, Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley import logs, services
from ashley.channels.model import Inbound, Outbound
from ashley.channels.respond import respond
from ashley.errands.config import CONFIG
from ashley.errands.errands import Errands, ErrandsUnavailable
from ashley.errands.model import Counts, Done, Errand, Reason, State
from ashley.inference.model import Message, Prompt
from ashley.inference.reply import Reply
from ashley.persona import persona
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from contract.conversations_support import events
from respond_support import ALANA, HOME, SAM, Fakes, FakeTools, inbound, wired as wired

__all__ = ["ALANA", "HOME", "SAM", "Fakes", "wired", "inbound"]

HOUSE = "house"
SEARCH = "search"
TELL_MAX = CONFIG.tell_max
HEADING = "# While they were away"
MARK = "zqOWED7731"


# --- ASSUMPTIONS: change here only -------------------------------------------------------------------------------


def reply(owed: str | None = None, text: str = "It is done.") -> Reply:
    """A reply that sets `Reply.owed` to `owed` (the field is named `owed`, a string or null)."""
    return Reply.model_validate({"spoken": text, "text": text, "owed": owed})


def held_aside() -> Reply:
    """A reply that is not the answer: on a channel that takes later replies it is the held first line."""
    return Reply(answers=False, spoken="One moment.", text="One moment.")


def owed_of(done: dict[str, str]) -> str:
    """The `owed` field of a `respond.done` line: the source key kept, `none` when nothing was owed."""
    return done["owed"]


NOTHING_OWED = "none"


def dropped_of(done: dict[str, str]) -> int:
    """The `owed_dropped` field of a `respond.done` line: 1 when the model's `owed` was dropped, else 0."""
    return int(done["owed_dropped"])


def told_of(done: dict[str, str]) -> tuple[int, ...]:
    """The `told` field of a `respond.done` line: the errand ids as a comma-separated list, empty when none."""
    raw = done.get("told", "")
    return tuple(int(part) for part in raw.split(",") if part)


# Where the prompt carries a told result: anywhere in the system prompt or the messages sent to Inference.
def prompt_text(prompt: Prompt) -> str:
    return "\n".join([*(variant.text for variant in prompt.system.values()),
                      *(m.text for m in prompt.messages if isinstance(m, Message))])


# --- fakes ------------------------------------------------------------------------------------------------------


@dataclass
class FakeErrands(Errands):
    """Records `owe`, `untold` and `told` calls. `waiting` is what `untold` answers (oldest first), cut to `limit`
    and without what `told` already marked; `trace` is shared with the conversations to show the order of events."""

    waiting: list[Done] = field(default_factory=list[Done])
    owed: list[tuple[int, int, int, int, str]] = field(default_factory=list[tuple[int, int, int, int, str]])
    untold_calls: list[tuple[int, int, bool]] = field(default_factory=list[tuple[int, int, bool]])
    told_calls: list[tuple[int, ...]] = field(default_factory=list[tuple[int, ...]])
    trace: list[str] = field(default_factory=list[str])
    fail_owe: bool = False
    fail_untold: bool = False
    fail_told: bool = False

    async def owe(self, household_id: int, asker_id: int, conversation_id: int, turn_id: int, source: str) -> int:
        self.trace.append("owe")
        if self.fail_owe:
            raise ErrandsUnavailable("down")
        self.owed.append((household_id, asker_id, conversation_id, turn_id, source))
        return len(self.owed)

    async def untold(self, hearer: int, limit: int, owner_only: bool = True) -> tuple[Done, ...]:
        self.trace.append("untold")
        self.untold_calls.append((hearer, limit, owner_only))
        if self.fail_untold:
            raise ErrandsUnavailable("down")
        return tuple(self.waiting[:limit])

    async def told(self, errand_ids: Collection[int]) -> None:
        self.trace.append("told")
        if self.fail_told:
            raise ErrandsUnavailable("down")
        self.told_calls.append(tuple(errand_ids))
        self.waiting = [d for d in self.waiting if d.id not in set(errand_ids)]

    async def claim(self, answering: Collection[str], max_age_s: float) -> Errand | None:
        raise AssertionError("respond never claims")

    async def due_sources(self, max_age_s: float) -> frozenset[str]:
        raise AssertionError("respond never asks what is due")

    async def release(self, errand_id: int, attempt: int, max_attempts: int) -> State:
        raise AssertionError("respond never releases")

    async def finish(self, errand_id: int, attempt: int, result: str) -> None:
        raise AssertionError("respond never finishes")

    async def give_up(self, errand_id: int, attempt: int, reason: Reason) -> None:
        raise AssertionError("respond never gives up")

    async def sweep(self, claim_s: float, max_age_s: float) -> Counts:
        raise AssertionError("respond never sweeps")

    @property
    def told_ids(self) -> list[int]:
        return [i for call in self.told_calls for i in call]


@dataclass
class SourceTools(FakeTools):
    """The catalogue with chosen `unreachable` source keys; `reachable` False means no source answered."""

    unreachable: tuple[str, ...] = ()

    async def catalogue(self) -> Catalogue:
        if not self.reachable:
            raise ToolsUnavailable("down")
        return Catalogue(self.specs, "use the tools", self.unreachable)


@dataclass
class World:
    fakes: Fakes
    errands: FakeErrands
    tools: SourceTools

    def say(self, *script: Any) -> None:
        self.fakes.inference.script = list(script)

    def person_turn_id(self) -> int:
        conv = next(iter(self.fakes.conversations.convs.values()))
        return next(t.id for t in conv.turns if t.author == "person")

    def conversation_id(self) -> int:
        return next(iter(self.fakes.conversations.convs))


def done(id_: int, result: str, asker_id: int = ALANA.id, source: str = HOUSE, visibility: str = "shared") -> Done:
    assert visibility in ("shared", "private")
    return Done(id_, asker_id, source, result, "shared" if visibility == "shared" else "private",
                datetime(2026, 11, 1, tzinfo=UTC))


def alana(**changes: Any) -> Inbound:
    """A message from Alana by id, on a household-audience device."""
    return replace(inbound(speaker_id=ALANA.id), **changes)


def owner_alone(**changes: Any) -> Inbound:
    """A message from Alana on a channel only he hears."""
    return replace(inbound(speaker_id=ALANA.id), audience="owner", shared=False, place=None, channel="web", **changes)


@pytest.fixture
def world(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    """The respond fakes with the real `persona.system` (the prompt text is the contract), a catalogue whose
    unreachable sources a test sets, and a recording Errands that shares a trace with her stored turns."""
    monkeypatch.setattr(persona, "system", _REAL_SYSTEM)
    tools = SourceTools()
    wired.tools = tools
    services.register(Tools, tools)
    errands = FakeErrands()
    services.register(Errands, errands)
    original = wired.conversations.add_turn

    async def traced(conversation_id: int, turn: Any) -> Any:
        stored = await original(conversation_id, turn)
        if turn.author == "ashley":
            errands.trace.append("stored")
        return stored

    monkeypatch.setattr(wired.conversations, "add_turn", traced)
    logs.setup()
    yield World(wired, errands, tools)
    services.unregister(Errands)


_REAL_SYSTEM = persona.system


def speak(message: Inbound) -> Outbound:
    return asyncio.run(respond(message))


def done_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, str]]:
    return events(capsys.readouterr().out, "respond.done")
