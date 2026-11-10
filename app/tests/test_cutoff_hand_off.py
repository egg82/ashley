"""On a turn that offers `bench_hand_off`, a step cut off at the token limit is asked again with the note that names the
tool (`unsaid.TOO_BIG_HAND_OFF`), under `auto`; the long-turn hand-off note (`unsaid.HAND_OFF`) then never follows on
the same turn. A turn without the tool gets the plain note."""

import asyncio
import dataclasses
from dataclasses import dataclass

from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.limits import Limits
from ashley.channels.steps import Steps
from ashley.inference.inference import Inference, InferenceCutOff
from ashley.inference.model import Message, Prompt, SystemPrompt, ToolCalls, ToolSpec
from ashley.inference.reply import Reply
from pydantic import BaseModel
from respond_support import Fakes, FakeInference, calls, wired as wired

SYSTEM = {"default": SystemPrompt("s")}
HISTORY = (Message("person", "build the whole app"),)
FINAL = Reply(spoken="Handed off.", text="Handed off.")
LIMITS = Limits(10, 8000, 1, 0)
CUT = InferenceCutOff("cut off")
HAND_OFF_TOOL = ToolSpec("bench_hand_off", "hands work to a worker", {"type": "object", "properties": {}})


@dataclass
class Counting(Steps):
    """A turn's count of cut-off re-asks, as `Saved` keeps it."""

    seen: int = 0

    @property
    def cut_off(self) -> int:
        return self.seen

    async def cut(self) -> None:
        self.seen += 1


def run(wired: Fakes, script: list[ToolCalls | BaseModel | Exception], limits: Limits = LIMITS,
        offered: bool = True) -> FakeInference:
    inference = FakeInference(script=script)
    services.register(Inference, inference)
    tools = (*wired.tools.specs, HAND_OFF_TOOL) if offered else wired.tools.specs
    got = asyncio.run(tool_loop.answer("brainstorm", SYSTEM, HISTORY, tools, limits, 7, source=wired.tools,
                                       steps=Counting()))
    assert isinstance(got, tool_loop.Answer) and got.reply.text == FINAL.text
    return inference


def notes(prompt: Prompt) -> list[Message]:
    kept = (unsaid.TOO_BIG, unsaid.TOO_BIG_HAND_OFF, unsaid.HAND_OFF)
    return [m for m in prompt.messages if isinstance(m, Message) and m in kept]


def test_a_cut_off_bench_turn_is_asked_again_naming_the_hand_off_under_auto(wired: Fakes) -> None:
    inference = run(wired, [CUT, FINAL])
    first, again = inference.prompts
    assert again.messages == (*first.messages, unsaid.TOO_BIG_HAND_OFF)
    assert again.tools == first.tools and again.tool_choice == "auto"


def test_a_turn_without_the_tool_gets_the_plain_note(wired: Fakes) -> None:
    inference = run(wired, [CUT, FINAL], offered=False)
    assert inference.prompts[1].messages[-1] == unsaid.TOO_BIG


def test_after_the_cut_off_note_the_long_turn_note_never_follows(wired: Fakes) -> None:
    limits = dataclasses.replace(LIMITS, hand_off_after_rounds=1)
    inference = run(wired, [CUT, calls("lights", prefix="a-"), calls("lights", prefix="b-"), FINAL], limits)
    assert [notes(p) for p in inference.prompts] == [[], [unsaid.TOO_BIG_HAND_OFF], [], []]
    assert {p.tool_choice for p in inference.prompts} == {"auto"}


def test_a_turn_told_to_hand_off_and_then_cut_off_is_asked_again_naming_it(wired: Fakes) -> None:
    limits = dataclasses.replace(LIMITS, hand_off_after_rounds=1)
    inference = run(wired, [calls("lights"), CUT, FINAL], limits)
    assert [notes(p) for p in inference.prompts] == [[], [unsaid.HAND_OFF], [unsaid.HAND_OFF, unsaid.TOO_BIG_HAND_OFF]]


def test_the_cut_off_note_names_the_tool_the_choice_is_keyed_on() -> None:
    assert HAND_OFF_TOOL.name in unsaid.TOO_BIG_HAND_OFF.text and HAND_OFF_TOOL.name not in unsaid.TOO_BIG.text
