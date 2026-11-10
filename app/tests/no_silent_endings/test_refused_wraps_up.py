"""A refusal after the first line went out is wrapped up on another route, and when that fails too, ends in the fixed
line: a held turn is never left with only its held line."""

import pytest
from ashley import services
from ashley.channels import tool_loop, unsaid
from ashley.channels.respond import respond
from ashley.channels.tool_loop import Held, Steps
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Entry, Message
from ashley.inference.reply import Reply
from ashley.tools.tools import Tools
from contract.conversations_support import events, run
from no_silent_endings_support import (CHECKING, HISTORY, SYSTEM, WRAPPED, Model, Scripted, Switch, World, database, limits,
                                        settled)


def resumed() -> tool_loop.Answer:
    got: list[tool_loop.Answer] = []

    async def go() -> None:
        services.register(Tools, Switch())
        try:
            got.append(await tool_loop.resume(Held(CHECKING, HISTORY, 0, 0), "chat", SYSTEM, (), limits(), 7))
        finally:
            services.unregister(Tools)

    run(go())
    return got[0]


def test_a_refusal_after_the_held_line_is_wrapped_up_on_the_wrap_up_route(
        loop: Model, capsys: pytest.CaptureFixture[str]) -> None:
    loop.play(InferenceRefused("declined"), WRAPPED)
    assert resumed().reply == WRAPPED
    assert loop.tasks == ["chat", "wrap_up"]
    last = loop.prompts[-1]
    assert last.tool_choice == "none" and last.messages[-1] == unsaid.ASK
    (line,) = events(capsys.readouterr().out, "respond.ended")
    assert (line["reason"], line["recovery"], line["conversation"]) == ("refused", "wrap_up", "7")


@pytest.mark.parametrize("second", [InferenceRefused("again"), InferenceUnavailable("none answered"),
                                    Reply(spoken="", text="")], ids=["refused", "unavailable", "empty"])
def test_a_wrap_up_that_fails_too_is_the_fixed_line(
        loop: Model, capsys: pytest.CaptureFixture[str], second: Scripted) -> None:
    loop.play(InferenceRefused("declined"), second)
    assert resumed().reply == unsaid.fixed()
    (line,) = events(capsys.readouterr().out, "respond.ended")
    assert line["recovery"] == "fixed_line"


class Handing(Steps):
    """Hands the turn one message, the first time it is asked after a draft of hers."""

    def __init__(self) -> None:
        self.handed = False

    async def steer(self, entries: tuple[Entry, ...], rounds: int, calls: int) -> tuple[Message, ...]:
        last = entries[-1] if entries else None
        if self.handed or not (isinstance(last, Message) and last.author == "ashley"):
            return ()
        self.handed = True
        return (Message("person", "and the porch too"),)


def test_a_wrap_up_after_a_message_handed_to_the_turn_sees_the_draft_and_the_message(loop: Model) -> None:
    loop.play(Reply(spoken="A.", text="A."), InferenceRefused("declined"), WRAPPED)

    async def go() -> None:
        services.register(Tools, Switch())
        try:
            await tool_loop.resume(Held(CHECKING, HISTORY, 0, 0), "chat", SYSTEM, (), limits(), 7, steps=Handing())
        finally:
            services.unregister(Tools)

    run(go())
    assert loop.tasks == ["chat", "chat", "wrap_up"]
    assert loop.prompts[-1].messages[-3:] == (Message("ashley", "A."), Message("person", "and the porch too"), unsaid.ASK)


def test_a_refusal_with_no_held_line_still_raises(loop: Model) -> None:
    loop.play(InferenceRefused("declined"))

    async def go() -> None:
        services.register(Tools, Switch())
        try:
            with pytest.raises(InferenceRefused):
                await tool_loop.answer("chat", SYSTEM, HISTORY, (), limits(), 7)
        finally:
            services.unregister(Tools)

    run(go())
    assert loop.tasks == ["chat"]


def test_a_held_web_turn_refused_after_its_line_is_stored_as_the_wrap_up(world: World) -> None:
    world.model.play(CHECKING, InferenceRefused("declined"), WRAPPED)

    async def go() -> None:
        async with database(world):
            await respond(world.inbound())
            await settled(world, 2)

    run(go())
    assert world.hers() == [(CHECKING.text, True), (WRAPPED.text, False)]
    assert world.work() == 0 and world.model.tasks == ["chat", "chat", "wrap_up"]
