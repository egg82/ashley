"""A message handed to a turn after its draft at the closing step (round `max_tool_rounds`) leaves the turn there: the
next step is the closing one again and the checkpointed round is the closing round, so a runner that resumes it steps
instead of finding the loop spent."""

import asyncio

import pytest
from ashley.channels import tool_loop
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Steps
from ashley.inference.model import Entry, Message, SystemPrompt
from ashley.inference.reply import Reply
from respond_support import Fakes, calls, wired as wired


class Handing(Steps):
    """Hands the turn one message the first time it is asked after a draft of hers; records the round each was saved at."""

    def __init__(self) -> None:
        self.saved: list[int] = []

    async def steer(self, entries: tuple[Entry, ...], rounds: int, calls: int) -> tuple[Message, ...]:
        last = entries[-1] if entries else None
        if not (isinstance(last, Message) and last.author == "ashley"):
            return ()
        self.saved.append(rounds)
        return (Message("person", "and the porch too"),) if len(self.saved) == 1 else ()


@pytest.mark.parametrize("max_rounds", [1, 3])
def test_a_message_handed_after_the_closing_draft_is_answered_by_another_closing_step(
        wired: Fakes, max_rounds: int) -> None:
    wired.inference.script = [*[calls("lights", prefix=f"r{i}") for i in range(max_rounds)],
                              Reply(spoken="A.", text="A."), Reply(spoken="B.", text="B.")]
    handing = Handing()
    got = asyncio.run(tool_loop.answer(
        "chat", {"default": SystemPrompt("s")}, (Message("person", "hi"),), wired.tools.specs,
        Limits(max_rounds, 8000, 1, 0), 7, source=wired.tools, steps=handing, medium="text"))
    assert isinstance(got, tool_loop.Answer) and got.reply.text == "B."
    assert handing.saved == [max_rounds, max_rounds]
    assert [p.tool_choice for p in wired.inference.prompts][-2:] == ["none", "none"]
