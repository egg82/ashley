"""Her `find` tool and the `cites` of her reply: the tool asks each source for the turn's hearer, so a reply that does
not reach the speaker alone never asks the ledger or their conversations; each record carries a number from the turn's
count, and her reply keeps on her turn (`shown`) only the records it cites that a call of this turn returned, as the
card each is drawn as."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels import checkpoint, turn_tools
from ashley.channels.landing import Landing
from ashley.channels.model import Inbound
from ashley.channels.respond import LIMITS, respond
from ashley.channels.tool_loop import Progress
from ashley.conversations.model import Match, Shown
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from ashley.ledger import model as ledger
from ashley.ledger.ledger import Ledger, NullLedger
from ashley.memory.memory import Memory, NullMemory
from ashley.memory.model import Asker, Fact, Recalled
from ashley.receipts import Citable
from respond_support import ALANA, EPOCH, Fakes, inbound, wired as wired

KEY = Fact(7, 10, ALANA.id, ALANA.id, "shared", "plan", False, "the spare key is under the blue pot", 1, EPOCH, None, None)


class OneFact(NullMemory):
    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        return (Recalled(KEY, True),)


@dataclass
class AskedLedger(NullLedger):
    asked: list[str] = field(default_factory=list[str])

    async def transactions(self, household_id: int, query: ledger.TransactionQuery) -> ledger.Page[ledger.Entry]:
        self.asked.append(query.search or "")
        return ledger.Page((), 0)


@pytest.fixture
def sources(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> Generator[AskedLedger]:
    """Memory recalls `KEY`; the ledger records what it was asked; the speaker's conversations hold one turn."""
    found = AskedLedger()
    services.register(Memory, OneFact())
    services.register(Ledger, found)

    async def search(household_id: int, person_id: int, query: str, limit: int) -> tuple[Match, ...]:
        found.asked.append(f"conversations:{query}")
        return (Match(3, 30, datetime(2026, 11, 1, tzinfo=UTC), "person", "the key", 1.0),)

    monkeypatch.setattr(wired.conversations, "search", search)
    yield found
    services.unregister(Memory)
    services.unregister(Ledger)


def alone() -> Inbound:
    return replace(inbound("where is the key", thread=f"person:{ALANA.id}:web", shared=False, speaker_id=ALANA.id,
                           kind="chat"), audience="owner")


def finds(query: str = "key", prefix: str = "f") -> ToolCalls:
    return ToolCalls((ToolCall(f"{prefix}0", "find", {"query": query}),))


def said(*cites: int) -> Reply:
    return Reply(spoken="It is under the blue pot.", text="It is under the blue pot.", cites=cites)


def hers(wired: Fakes) -> tuple[Shown, ...]:
    [turn] = [t for t in wired.conversations.added if t.author == "ashley"]
    return turn.shown


def test_a_reply_not_reaching_the_speaker_alone_never_asks_the_ledger_or_their_conversations(sources: AskedLedger) -> None:
    shared = replace(alone(), shared=True)
    got = asyncio.run(turn_tools.for_turn(shared).call(ToolCall("f0", "find", {"query": "key"})))
    body = json.loads(got.content)
    assert sources.asked == []
    assert body["answered"] == ["memory"] and [r["kind"] for r in body["records"]] == ["memory"]
    asyncio.run(turn_tools.for_turn(alone()).call(ToolCall("f1", "find", {"query": "key"})))
    assert sorted(sources.asked) == ["conversations:key", "key"]


def test_records_her_reply_cites_are_kept_on_her_turn_as_their_cards(wired: Fakes, sources: AskedLedger) -> None:
    wired.inference.script = [finds(), said(1)]
    asyncio.run(respond(alone()))
    assert hers(wired) == (Shown("fact", "7"),)


def test_a_cite_of_a_number_no_call_returned_is_dropped(wired: Fakes, sources: AskedLedger) -> None:
    wired.inference.script = [finds(), said(9, 1, 1)]
    asyncio.run(respond(alone()))
    assert hers(wired) == (Shown("fact", "7"),)


def test_a_returned_record_she_does_not_cite_is_not_kept(wired: Fakes, sources: AskedLedger) -> None:
    wired.inference.script = [finds(), said()]
    asyncio.run(respond(alone()))
    assert hers(wired) == ()


def test_a_turn_with_no_find_call_keeps_no_cites(wired: Fakes, sources: AskedLedger) -> None:
    wired.inference.script = [said(1, 2)]
    asyncio.run(respond(alone()))
    assert hers(wired) == ()


def test_each_record_of_a_turn_has_its_own_number(sources: AskedLedger) -> None:
    landing = Landing(alone(), (1, 2), LIMITS)
    first = json.loads(asyncio.run(landing.call(ToolCall("f0", "find", {"query": "key"}))).content)
    second = json.loads(asyncio.run(landing.call(ToolCall("f1", "find", {"query": "pot"}))).content)
    numbers = [r["n"] for r in (*first["records"], *second["records"])]
    assert numbers == [1, 2, 3, 4]
    assert [r["kind"] for r in first["records"]] == ["memory", "conversation"]
    assert landing.kept(said(2, 3)) == (Shown("fact", "7"),)


def test_a_resumed_turn_still_checks_cites_against_what_its_earlier_calls_returned() -> None:
    result = ToolResult("f0", "{}", citable=(Citable(1, Shown("fact", "7")), Citable(2, None)))
    progress = Progress((Message("person", "hello"), ToolCalls((ToolCall("f0", "find", {"query": "k"}),)),
                         ToolResults((result,))), 1, 1)
    text = checkpoint.dumps(checkpoint.Checkpoint(inbound("hello"), 1, 2, 1, {"default": SystemPrompt("s")}, progress))
    landing = Landing(alone(), (1, 2), LIMITS)
    landing.resuming(checkpoint.loads(text).progress.entries, {})
    assert landing.kept(said(2, 1, 5)) == (Shown("fact", "7"),)
    assert landing.results.next_number() == 3
