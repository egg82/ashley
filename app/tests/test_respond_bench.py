"""A bench's talk through the turn loop: she is offered the shared tools and then the bench's, and a bench tool she
calls reaches the Workshop as her command on the speaker's bench, in the reply and in the answer a held reply stood
for; the shared tools never see it."""

import asyncio
from dataclasses import replace

from ashley import services
from ashley.channels.respond import respond
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.workshop.commands import Remove
from ashley.workshop.model import HER, Owner
from ashley.workshop.workshop import Workshop
from bench_tools_support import FakeWorkshop
from later_support import until
from respond_support import ALANA, HOME, Fakes, inbound, wired as wired

REPLY = Reply(spoken="Done.", text="Done.")
ASKED = 100
"""The id the conversation fake gives the person's turn, the first it stores; her commands carry it."""
BENCH = replace(inbound(thread="bench:4", speaker_id=ALANA.id, kind="brainstorm"), audience="owner", shared=False,
                place=None, channel="web", bench_id=4)


def remove(piece_id: int) -> ToolCalls:
    return ToolCalls((ToolCall("b1", "bench_remove", {"piece_id": piece_id}),))


def test_a_bench_tool_she_calls_reaches_the_workshop_as_her_command_on_the_speakers_bench(wired: Fakes) -> None:
    shop = FakeWorkshop()
    services.register(Workshop, shop)
    wired.inference.script = [remove(3), REPLY]
    asyncio.run(respond(BENCH))
    assert shop.applied == [(Owner(HOME.id, ALANA.id), 4, Remove(replace(HER, turn=ASKED), 3))]
    assert wired.tools.called == []
    offered = [s.name for s in wired.inference.prompts[0].tools]
    assert offered[0] == "lights" and "bench_remove" in offered


def test_the_answer_a_held_reply_stood_for_reaches_the_bench_too(wired: Fakes) -> None:
    shop = FakeWorkshop()
    services.register(Workshop, shop)
    wired.inference.script = [Reply(answers=False, spoken="One moment.", text="One moment."), remove(5), REPLY]

    async def scenario() -> None:
        out = await respond(replace(BENCH, later=True, later_by="turn"))
        assert out.follows
        await until(lambda: shop.applied)

    asyncio.run(scenario())
    assert shop.applied == [(Owner(HOME.id, ALANA.id), 4, Remove(replace(HER, turn=ASKED), 5))]
