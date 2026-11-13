"""A turn that held a call is made worth saying (a woken one goes out), and one that only did something is not."""

from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels.landing import Landing
from ashley.initiative.initiative import Initiative
from initiative_support import speaking
from ashley.inference.reply import Reply
from ashley.senses.outside_record import DoneAction, OutsideRecord
from ashley.senses.proposals import Proposals
from contract.conversations_support import run
from outside_record_support import MemoryRecord
from receipts_blind_support import LAMP_LABEL, World, change, database, play
from receipts_blind_unit_support import CONVERSATION, HOUSEHOLD, LIMITS, SPEAKER, TURN, WEB, Numbered

QUIET_REPLY = Reply(spoken="Handled.", text="Handled.", says="none")


@pytest.fixture(autouse=True)
def initiative() -> Generator[None]:
    services.register(Initiative, speaking())
    yield
    services.unregister(Initiative)


def test_a_turn_that_only_did_something_is_not_made_worth_saying(world: World) -> None:
    async def go() -> None:
        records = MemoryRecord()
        services.register(OutsideRecord, records)
        services.register(Proposals, Numbered())
        try:
            await records.done(DoneAction(HOUSEHOLD, SPEAKER, CONVERSATION, TURN, "house_do", LAMP_LABEL, "judged",
                                          "asked_directly", "You asked.", datetime.now(UTC), LAMP_LABEL))
            landing = Landing(replace(WEB, taint="watch"), (CONVERSATION, TURN), LIMITS)
            closed = await landing.closing(QUIET_REPLY)
            assert closed.says == "none" and closed.text == QUIET_REPLY.text
            assert landing.receipts is not None and [r.headline for r in landing.receipts.done] == [LAMP_LABEL]
        finally:
            services.unregister(OutsideRecord)
            services.unregister(Proposals)

    run(go())


def test_a_woken_turn_that_holds_a_call_goes_out_though_she_set_worth_saying_false(world: World) -> None:
    world.phone()
    world.judge.answers = {"house_do": "ask"}
    woken = replace(world.web(), unprompted=True, author="household", taint="watch", later=False)

    async def go() -> None:
        async with database(world):
            played = await play(world, woken, [change(), QUIET_REPLY])
            assert played.out.says == "reply" and played.answer.text == "Handled."
            assert played.answer.receipts is not None and played.answer.receipts.held

    run(go())
