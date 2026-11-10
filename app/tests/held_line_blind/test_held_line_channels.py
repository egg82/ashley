"""A held line on a channel delivering through the outbox and on one whose reply is the stored turn, with in-memory
fakes: it is stored as her turn marked `follows` with the delivered field, heard as the person's turn was; the answer
is stored separately, not `follows`; a failing store loses neither the line nor the answer."""

from dataclasses import replace

from collections.abc import Callable

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.conversations.inflight import Claim, InFlight, NullInFlight
from ashley.conversations.model import NewTurn, Turn
from ashley.inference.reply import Reply
from contract.inference_support import settle
from contract.turns_support import ALANA, World, inbound, world as world
from later_support import FakeOutbox, until
from later_support import outbox as outbox

CHECKING = Reply(answers=False, spoken="Let me check, spoken.", text="Let me *check*, text.")
FINAL = Reply(spoken="No rain, spoken.", text="No rain, text.")


def later(**changes: object) -> Inbound:
    return replace(inbound(thread="discord:1001", kind="chat", medium="text", place=None, speaker_id=ALANA.id),
                   later=True, **changes)


def hers(world: World, conversation_id: int) -> list[tuple[str, bool]]:
    return [(t.text, t.follows) for t in world.conversations.stored[conversation_id].turns if t.author == "ashley"]


@pytest.mark.parametrize(("medium", "held", "answer"), [("text", CHECKING.text, FINAL.text),
                                                        ("spoken", CHECKING.spoken, FINAL.spoken)])
def test_the_held_line_and_the_answer_are_stored_as_the_delivered_field(
        world: World, outbox: FakeOutbox, medium: str, held: str, answer: str) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def go() -> None:
        out = await respond(later(medium=medium))
        assert hers(world, out.conversation_id) == [(held, True)]
        await until(lambda: outbox.added)
        await until(lambda: len(hers(world, out.conversation_id)) == 2)
        assert hers(world, out.conversation_id) == [(held, True), (answer, False)]

    settle(go())


def test_the_held_line_is_stored_before_respond_returns_and_the_answer_is_one_more_turn(
        world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def go() -> None:
        out = await respond(later())
        stored = world.conversations.stored[out.conversation_id].turns
        assert [(t.author, t.follows) for t in stored] == [("person", False), ("ashley", True)]
        await until(lambda: outbox.added)

    settle(go())
    assert [t.follows for _, t in world.conversations.added] == [False, True, False]


def test_the_held_line_is_heard_as_the_persons_turn_was(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def go() -> None:
        await respond(later(audience="owner"))
        await until(lambda: outbox.added)

    settle(go())
    said, held, answer = (t for _, t in world.conversations.added[:3])
    assert (held.author, held.follows, held.speaker_id) == ("ashley", True, None)
    assert (held.heard, held.owner_id) == (said.heard, said.owner_id) == (answer.heard, answer.owner_id)


def test_a_person_turn_is_never_marked_follows(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL, FINAL]

    async def go() -> None:
        await respond(later())
        await until(lambda: outbox.added)
        await respond(later())

    settle(go())
    assert [t.follows for _, t in world.conversations.added if t.author == "person"] == [False, False]


def test_a_reply_that_is_the_answer_is_not_marked(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [FINAL]
    out = settle(respond(later()))
    assert hers(world, out.conversation_id) == [(FINAL.text, False)]


class Recording(NullInFlight):
    """Stores as the null one does, recording which of `said` and `finish` stored each turn."""

    def __init__(self) -> None:
        self.stored: list[tuple[str, Claim, NewTurn]] = []

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        self.stored.append(("said", claim, turn))
        return await super().said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        self.stored.append(("finish", claim, turn))
        return await super().finish(claim, turn, after)


def test_on_web_chat_the_held_line_is_said_and_the_answer_finishes_the_work(world: World) -> None:
    recording = Recording()
    services.register(InFlight, recording)
    world.inference.script = [CHECKING, FINAL]

    async def go() -> None:
        out = await respond(later(thread="person:11:web", later_by="turn"))
        assert out.follows
        await until(lambda: len(recording.stored) == 2)

    settle(go())
    (first, claim, held), (second, finished, answer) = recording.stored
    assert (first, held.follows, held.text) == ("said", True, CHECKING.text)
    assert (second, answer.follows, answer.text) == ("finish", False, FINAL.text)
    assert claim == finished
