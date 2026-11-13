"""`Landing` with `Outside` in front: who may agree, what a turn that held shows beside her reply, and that a moved page
leaves the same `Outside` in place."""

from dataclasses import replace

from ashley import services
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.channels.standing import of
from ashley.inference.reply import Reply
from ashley.inference.model import ToolCall
from ashley.senses.proposal_payloads import OUTSIDE, HeldCall, HeldCalls
from ashley.senses.proposals import Proposal, Proposals
from outside_ask_support import HOUSEHOLD, SPEAKER, Memory, run
from datetime import UTC, datetime

LIMITS = load_limits()
WEB = Inbound(household_id=HOUSEHOLD, thread="person:7:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=SPEAKER, shared=False, place=None, channel="web", taint=None)


def test_only_an_untainted_person_turn_that_reaches_the_speaker_alone_may_agree() -> None:
    own = of(WEB)
    assert own is not None and own.agreeing and own.private
    for changed in ({"taint": "stranger"}, {"author": "household"}):
        standing = of(replace(WEB, **changed))
        assert standing is not None and not standing.agreeing
    shared = of(replace(WEB, shared=True))
    assert shared is not None and not shared.private
    assert of(replace(WEB, speaker_id=None)) is None


def test_a_turn_that_held_keeps_her_words_and_receipts_beside_them_and_is_worth_saying() -> None:
    async def go() -> None:
        memory = Memory()
        services.register(Proposals, memory)
        landing = Landing(replace(WEB, taint="watch"), (40, 100), LIMITS)
        now = datetime.now(UTC)
        calls = HeldCalls((HeldCall("lamp", {"room": "porch"}, 'lamp (room: "porch")'),))
        await memory.propose(Proposal(HOUSEHOLD, SPEAKER, 40, 100, now, calls), 60)
        reply = Reply(spoken="s", text="I looked.", says="none")
        closed = await landing.closing(reply)
        assert closed.text == "I looked." and closed.spoken == "s" and closed.says == "reply" and landing.held == 1
        assert landing.receipts is not None and [h.detail for h in landing.receipts.held] == ['lamp (room: "porch")']
        assert landing.agree == landing.receipts.proposal_id == 1

    run(go())


def test_a_turn_that_held_nothing_is_stored_as_she_said_it() -> None:
    async def go() -> None:
        services.register(Proposals, Memory())
        landing = Landing(WEB, (40, 100), LIMITS)
        reply = Reply(spoken="s", text="hello", says="none")
        assert await landing.closing(reply) == reply and landing.held == 0

    run(go())


def test_a_resumed_landing_starts_with_the_taint_the_checkpoint_had() -> None:
    async def call_lamp(landing: Landing) -> None:
        await landing.call(ToolCall("c", "mystery_change", {}))

    async def go() -> None:
        memory = Memory()
        services.register(Proposals, memory)
        for landing in (Landing(WEB, (40, 100), LIMITS, "look_up"), Landing(replace(WEB, taint="watch"), (40, 100), LIMITS)):
            await call_lamp(landing)
        assert [c.tool for c in (await memory.pending(SPEAKER, 40, OUTSIDE) or Proposal(0, 0, 0, 0, datetime.now(UTC), HeldCalls(()))).payload.calls] == ["mystery_change"]

    run(go())
