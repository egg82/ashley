"""What her calls bring up (`ToolResult.shown`) is kept on the turn of hers she stores: each thing once, in the order
first brought up, never read from her words; a turn whose calls brought nothing up keeps none; a resumed turn keeps what
its calls made before the resume brought up, which a checkpoint carries."""

import asyncio
import json
from dataclasses import dataclass, replace

import pytest
from ashley import services
from ashley.channels import checkpoint
from ashley.channels.landing import Landing
from ashley.channels.model import Inbound
from ashley.channels.respond import LIMITS, respond
from ashley.channels.tool_loop import Progress
from ashley.conversations.model import Shown
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.tools import Tools
from respond_support import ALANA, Fakes, FakeTools, calls, inbound, wired as wired

A, B = Shown("printer", "01P"), Shown("printer", "02X")
READS = ToolSpec("printers", "the printers", {"type": "object"}, reads=True, outside=False)
PLAIN = ToolSpec("lights", "the lights", {"type": "object"}, reads=True, outside=False)


@dataclass
class BringsUp(FakeTools):
    """`printers` brings up A then B; any other tool brings up nothing."""

    async def call(self, call: ToolCall) -> ToolResult:
        got = await super().call(call)
        return replace(got, shown=(A, B)) if call.name == "printers" else got


@pytest.fixture
def tools(wired: Fakes) -> BringsUp:
    found = BringsUp(specs=(READS, PLAIN))
    services.register(Tools, found)
    return found


def hers(wired: Fakes) -> tuple[Shown, ...]:
    [turn] = [t for t in wired.conversations.added if t.author == "ashley"]
    return turn.shown


def asked() -> Inbound:
    return replace(inbound("show me the printer", thread=f"person:{ALANA.id}:web", speaker_id=ALANA.id, kind="chat"),
                   audience="owner")


def test_what_her_calls_brought_up_is_kept_on_her_turn_once_each_in_order(wired: Fakes, tools: BringsUp) -> None:
    wired.inference.script = [calls("printers", "lights"), calls("printers", prefix="d"), Reply(spoken="Here.", text="Here.")]
    asyncio.run(respond(asked()))
    assert hers(wired) == (A, B)


def test_a_turn_whose_calls_brought_nothing_up_keeps_none_whatever_she_says(wired: Fakes, tools: BringsUp) -> None:
    words = "Here is the printer card for 01P."
    wired.inference.script = [calls("lights"), Reply(spoken=words, text=words)]
    asyncio.run(respond(asked()))
    assert hers(wired) == ()


def test_a_resumed_turn_keeps_what_its_earlier_calls_brought_up() -> None:
    landing = Landing(inbound("show me", speaker_id=ALANA.id, kind="chat"), (1, 2), LIMITS)
    before = (Message("person", "show me"), ToolCalls((ToolCall("c0", "printers", {}),)),
              ToolResults((ToolResult("c0", "{}", shown=(B,)),)))
    landing.resuming(before, {"c1": ToolResult("c1", "{}", shown=(A, B))})
    assert landing.brought_up == (B, A)


def test_a_checkpoint_carries_what_a_result_brought_up() -> None:
    result = ToolResult("c0", "{}", shown=(A,))
    progress = Progress((Message("person", "hello"), ToolResults((result,))), 1, 1)
    text = checkpoint.dumps(checkpoint.Checkpoint(inbound("hello"), 1, 2, 1, {"default": SystemPrompt("s")}, progress))
    assert checkpoint.loads(text).progress.entries[1] == ToolResults((result,))
    raw = json.loads(text)
    for entry in raw["entries"]:
        for r in entry.get("results", ()):
            del r["shown"]
    old = checkpoint.loads(json.dumps(raw)).progress.entries[1]
    assert isinstance(old, ToolResults) and old.results[0].shown == ()
