"""`InFlight.said` and the `follows` mark, blind: a held line is stored as her turn while the claim holds, the work and
the claim kept; a claim that was lost writes nothing; `NullInFlight` stores through Conversations."""

import pytest
from ashley import services
from ashley.conversations.conversations import ConversationClosed, Conversations
from ashley.conversations.inflight import Claim, ClaimLost, InFlight, InFlightUnavailable
from ashley.conversations.model import Hearer, NewTurn, Turn
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import POLICY, place_before_now, run, scalar
from inflight_blind.ifb_support import rig

HELD = NewTurn("ashley", "Let me check.", follows=True)
ANSWER = NewTurn("ashley", "Dry all day.")


def test_a_new_turn_is_not_follows_unless_marked() -> None:
    assert NewTurn("ashley", "x").follows is False
    assert NewTurn("person", "x").follows is False
    assert NewTurn("ashley", "x", follows=True).follows is True


def test_said_stores_her_turn_marked_and_keeps_the_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            held = await r.inflight.said(claim, HELD)
            assert isinstance(held, Turn) and (held.author, held.text, held.follows) == ("ashley", HELD.text, True)
            assert await r.hers() == [HELD.text] and await r.rows() == 1
            assert scalar(db_url, "SELECT follows FROM turns WHERE id = %s", (held.id,)) is True

    run(go())


def test_the_answer_after_a_held_line_is_a_separate_turn_that_ends_the_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            held = await r.inflight.said(claim, HELD)
            answer = await r.inflight.finish(claim, ANSWER)
            assert answer.id > held.id and answer.follows is False
            assert await r.hers() == [HELD.text, ANSWER.text] and await r.rows() == 0
            conv = await r.conversations.get(claim.conversation_id)
            assert conv is not None
            assert [(t.author, t.follows) for t in conv.turns] == [("person", False), ("ashley", True), ("ashley", False)]

    run(go())


def test_several_held_lines_can_be_said_under_one_claim(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.said(claim, HELD)
            await r.inflight.said(claim, NewTurn("ashley", "Still looking.", follows=True))
            assert await r.hers() == [HELD.text, "Still looking."] and await r.rows() == 1

    run(go())


def test_said_renews_the_claim(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.lapse(claim, 1)
            await r.inflight.said(claim, HELD)
            assert await r.inflight.orphaned(5) == []

    run(go())


def test_said_after_the_claim_was_taken_by_another_runner_writes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.expire(claim)
            [taken] = await r.inflight.orphaned(5)
            with pytest.raises(ClaimLost):
                await r.inflight.said(claim, HELD)
            assert await r.hers() == [] and await r.rows() == 1
            await r.inflight.said(taken.claim, HELD)
            assert await r.hers() == [HELD.text]

    run(go())


@pytest.mark.parametrize("ended", ["finish", "drop"])
def test_said_after_the_work_ended_writes_nothing(db_url: str, ended: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            if ended == "finish":
                await r.inflight.finish(claim, ANSWER)
            else:
                await r.inflight.drop(claim)
            before = await r.hers()
            with pytest.raises(ClaimLost):
                await r.inflight.said(claim, HELD)
            assert await r.hers() == before

    run(go())


def test_said_into_a_closed_conversation_writes_nothing_and_keeps_the_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv = await r.conversations.for_thread(r.home, "cmd", "command", [r.who])
            said = await r.conversations.add_turn(conv.id, NewTurn("person", "hi", r.who))
            claim = await r.inflight.begin(conv.id, said.id, "cp")
            place_before_now(db_url, conv.id, 100_000)
            with pytest.raises(ConversationClosed):
                await r.inflight.said(claim, HELD)
            assert await r.hers() == [] and await r.rows() == 1

    run(go())


@pytest.mark.parametrize("bad", [NewTurn("ashley", "   ", follows=True), NewTurn("ashley", "", follows=True)])
def test_said_with_a_turn_conversations_refuses_is_a_value_error_and_keeps_the_work(db_url: str, bad: NewTurn) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            with pytest.raises(ValueError):
                await r.inflight.said(claim, bad)
            assert await r.hers() == [] and await r.rows() == 1

    run(go())


def test_said_with_a_person_turn_marked_follows_is_a_value_error(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            with pytest.raises(ValueError):
                await r.inflight.said(claim, NewTurn("person", "hi", r.who, follows=True))
            assert scalar(db_url, "SELECT count(*) FROM turns WHERE follows") == 0

    run(go())


def test_said_on_an_unreachable_database_is_unavailable() -> None:
    async def go() -> None:
        db = PoolDatabase(unreachable_conninfo(), connect_timeout_s=0.1)
        await db.open()
        try:
            with pytest.raises(InFlightUnavailable):
                await PostgresInFlight(db, POLICY, 15.0).said(Claim(1, 1, "h"), HELD)
        finally:
            await db.close()

    run(go())


def test_a_person_turn_marked_follows_is_refused_by_conversations(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv = await r.conversations.for_thread(r.home, "t1", "chat", [r.who])
            with pytest.raises(ValueError):
                await r.conversations.add_turn(conv.id, NewTurn("person", "hi", r.who, follows=True))
            got = await r.conversations.get(conv.id)
            assert got is not None and got.turns == ()

    run(go())


def test_the_mark_round_trips_through_every_read(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv = (await r.conversations.for_thread(r.home, "t1", "chat", [r.who])).id
            asked = await r.conversations.add_turn(conv, NewTurn("person", "rain today?", r.who, "shared"))
            held = await r.conversations.add_turn(conv, NewTurn("ashley", "Let me check.", heard="shared", follows=True))
            answer = await r.conversations.add_turn(conv, NewTurn("ashley", "Dry all day.", heard="shared"))
            later = await r.conversations.add_turn(conv, NewTurn("person", "and tomorrow?", r.who, "shared"))
            assert (asked.follows, held.follows, answer.follows) == (False, True, False)
            got = await r.conversations.get(conv)
            assert got is not None and [t.follows for t in got.turns] == [False, True, False, False]
            on = await r.conversations.on_thread(r.home, "t1")
            assert on is not None and [t.follows for t in on.turns] == [False, True, False, False]
            carried = await r.conversations.carried(Hearer(r.home, r.who, False), conv, later.id, "tomorrow", 10, 0)
            assert [(t.id, t.follows) for t in carried.recent] == [(asked.id, False), (held.id, True), (answer.id, False)]

    run(go())


def test_the_null_in_flight_says_through_conversations(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            services.register(Conversations, r.conversations)
            try:
                conv_id, said_id = await r.said()
                turn = await InFlight.null().said(Claim(said_id, conv_id, ""), HELD)
            finally:
                services.unregister(Conversations)
            assert (turn.text, turn.follows) == (HELD.text, True)
            got = await r.conversations.get(conv_id)
            assert got is not None and (got.turns[-1].text, got.turns[-1].follows) == (HELD.text, True)

    run(go())
