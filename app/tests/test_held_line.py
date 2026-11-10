"""A held line that went out is her turn: stored before the answer, marked `follows`, heard as the turn's other lines,
on a channel answering through the outbox and on one whose reply is the stored turn (through `InFlight.said`, under
the turn's claim); in Postgres the mark round-trips and `InFlight.said` writes nothing once the claim is lost."""

from dataclasses import replace

from collections.abc import Callable

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, ClaimLost, InFlight, NullInFlight
from ashley.conversations.model import Hearer, NewTurn, Turn
from ashley.inference.reply import Reply
from contract.conversations_support import run, scalar
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.inference_support import settle
from contract.turns_support import ALANA, World, inbound
from contract.turns_support import world as world
from inflight_blind.ifb_support import rig
from later_support import FakeOutbox, until
from later_support import outbox as outbox

CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
FINAL = Reply(spoken="No rain today.", text="No rain today.")


def later(**changes: object) -> Inbound:
    return replace(inbound(thread="discord:1001", kind="chat", medium="text", place=None, speaker_id=ALANA.id),
                   later=True, **changes)


def hers(world: World, conversation_id: int) -> list[tuple[str, bool]]:
    return [(t.text, t.follows) for t in world.conversations.stored[conversation_id].turns if t.author == "ashley"]


def test_the_held_line_is_stored_marked_before_the_answer(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def scenario() -> None:
        out = await respond(later())
        assert out.follows and out.body == CHECKING.text
        assert hers(world, out.conversation_id) == [(CHECKING.text, True)]
        await until(lambda: outbox.added)
        await until(lambda: len(hers(world, out.conversation_id)) == 2)
        assert hers(world, out.conversation_id) == [(CHECKING.text, True), (FINAL.text, False)]

    settle(scenario())


def test_the_held_line_is_heard_as_the_persons_turn_was(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def scenario() -> None:
        await respond(later(audience="owner"))
        await until(lambda: outbox.added)

    settle(scenario())
    said, held = (t for _, t in world.conversations.added[:2])
    assert (held.author, held.follows, held.speaker_id) == ("ashley", True, None)
    assert (held.heard, held.owner_id) == (said.heard, said.owner_id) == ("private", ALANA.id)


def test_the_held_line_and_the_answer_each_record_the_person_turn_they_answer(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def scenario() -> int:
        out = await respond(later())
        await until(lambda: len(hers(world, out.conversation_id)) == 2)
        return out.conversation_id

    out = settle(scenario())
    said, held, answer = world.conversations.stored[out].turns
    assert said.answers is None
    assert (held.answers, answer.answers) == (said.id, said.id)


def test_a_reply_that_is_the_answer_is_not_marked(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [FINAL]
    out = settle(respond(later()))
    assert hers(world, out.conversation_id) == [(FINAL.text, False)]


class RecordingInFlight(NullInFlight):
    """Stores as the null one does, recording which of `said` and `finish` stored each turn, in order."""

    def __init__(self) -> None:
        self.stored: list[tuple[str, Claim, NewTurn]] = []

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        self.stored.append(("said", claim, turn))
        return await super().said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        self.stored.append(("finish", claim, turn))
        return await super().finish(claim, turn, after)


def test_on_a_turn_channel_the_held_line_is_said_under_the_claim_and_the_answer_finishes_it(world: World) -> None:
    recording = RecordingInFlight()
    services.register(InFlight, recording)
    world.inference.script = [CHECKING, FINAL]

    async def scenario() -> None:
        await respond(later(thread="person:11:web", later_by="turn"))
        await until(lambda: len(recording.stored) == 2)

    settle(scenario())
    (first, claim, held), (second, finished, answer) = recording.stored
    assert (first, held.text, held.follows) == ("said", CHECKING.text, True)
    assert (second, answer.text, answer.follows) == ("finish", FINAL.text, False)
    assert claim == finished


def test_postgres_keeps_the_person_turn_an_answer_records_and_refuses_one_on_a_person_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            conv = (await r.conversations.for_thread(r.home, "t1", "chat", [r.who])).id
            first = await r.conversations.add_turn(conv, NewTurn("person", "rain today?", r.who, "shared"))
            held = await r.conversations.add_turn(conv, NewTurn("ashley", "Checking.", follows=True, answers=first.id))
            second = await r.conversations.add_turn(conv, NewTurn("person", "and tomorrow?", r.who, "shared"))
            answer = await r.conversations.add_turn(conv, NewTurn("ashley", "Dry.", answers=first.id))
            other = await r.conversations.add_turn(conv, NewTurn("ashley", "Hello."))
            with pytest.raises(ValueError):
                await r.conversations.add_turn(conv, NewTurn("person", "no", r.who, answers=first.id))
            got = await r.conversations.get(conv)
        assert (first.answers, held.answers, second.answers, answer.answers, other.answers) == (
            None, first.id, None, first.id, None)
        assert got is not None and [t.answers for t in got.turns] == [None, first.id, None, first.id, None]

    run(scenario())


def test_postgres_keeps_the_mark_through_every_read(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            conv = (await r.conversations.for_thread(r.home, "t1", "chat", [r.who])).id
            said = (await r.conversations.add_turn(conv, NewTurn("person", "rain today?", r.who, "shared"))).id
            held = await r.conversations.add_turn(conv, NewTurn("ashley", "Let me check.", heard="shared",
                                                                follows=True))
            answer = await r.conversations.add_turn(conv, NewTurn("ashley", "Dry all day.", heard="shared"))
            asked = await r.conversations.add_turn(conv, NewTurn("person", "and tomorrow?", r.who, "shared"))
            got = await r.conversations.get(conv)
            carried = await r.conversations.carried(Hearer(r.home, r.who, False), conv, asked.id, "tomorrow", 10, 0)
        assert (held.follows, answer.follows) == (True, False)
        assert got is not None and [t.follows for t in got.turns] == [False, True, False, False]
        assert [(t.id, t.follows) for t in carried.recent] == [(said, False), (held.id, True), (answer.id, False)]

    run(scenario())


def test_said_stores_her_turn_while_the_claim_holds_and_keeps_the_work(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            held = await r.inflight.said(claim, NewTurn("ashley", "Let me check.", follows=True))
            assert held.follows and await r.rows() == 1
            assert await r.hers() == ["Let me check."]
            await r.inflight.finish(claim, NewTurn("ashley", "Dry all day."))
            assert await r.hers() == ["Let me check.", "Dry all day."] and await r.rows() == 0

    run(scenario())


def test_said_once_the_claim_is_lost_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.expire(claim)
            assert len(await r.inflight.orphaned(5)) == 1
            with pytest.raises(ClaimLost):
                await r.inflight.said(claim, NewTurn("ashley", "Let me check.", follows=True))
            assert await r.hers() == []

    run(scenario())


def test_said_renews_the_claim(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.lapse(claim, 1)
            await r.inflight.said(claim, NewTurn("ashley", "Let me check.", follows=True))
            assert await r.inflight.orphaned(5) == []
            assert scalar(db_url, "SELECT count(*) FROM turn_work WHERE claimed_until > clock_timestamp()") == 1

    run(scenario())


def test_the_null_in_flight_says_through_conversations(world: World) -> None:
    conv = world.conversations.seed("t", "chat", [NewTurn("person", "hi")])
    turn = settle(InFlight.null().said(Claim(1, conv, ""), NewTurn("ashley", "Let me check.", follows=True)))
    assert turn.follows and services.get(Conversations) is world.conversations
    assert hers(world, conv) == [("Let me check.", True)]
