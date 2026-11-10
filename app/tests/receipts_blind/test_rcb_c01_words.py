"""Contract 1: code never writes into her turn. Whatever the channel, a stored turn of hers, the reply as it is returned
and each queued copy hold exactly what the model wrote, with no receipt string, headline or detail in them, whether the
turn did a judged change or held one."""

from dataclasses import replace

import pytest
from ashley.channels.model import Inbound
from ashley.conversations.model import Receipt, Receipts
from ashley.inference.reply import Reply
from contract.conversations_support import run
from receipts_blind_support import (ANSWER, CHECKING, OKAY, OLD_DONE_INTRO, OLD_HELD_INTRO, ROOM_PLANT, WHY_ASKED,
                                    WHY_RAN, World, change, database, looked, play, receipt_strings)
from receipts_blind_unit_support import WEB, held_landing

PHONE_ANSWER = Reply(spoken=OKAY, text=OKAY, to_phone=True)
CHANNELS = ["web", "discord", "voice", "phone_copy"]


def inbound_of(world: World, channel: str) -> Inbound:
    if channel == "web":
        return world.web()
    return world.discord() if channel == "discord" else world.voice()


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.parametrize("channel", CHANNELS)
def test_c01_nothing_code_wrote_is_in_her_turn_or_the_delivered_body(world: World, channel: str, held: bool) -> None:
    if held:
        world.judge.answers = {"house_do": "ask"}
    if channel in ("voice", "phone_copy"):
        world.phone()
    reply = PHONE_ANSWER if channel == "phone_copy" else ANSWER
    later = channel in ("web", "discord")
    script = [CHECKING, looked(), change(), reply] if later else [looked(), change(), reply]

    async def go() -> None:
        async with database(world):
            played = await play(world, inbound_of(world, channel), script)
            receipts = played.answer.receipts
            assert receipts is not None and (receipts.held if held else receipts.done), "the turn had something to show"
            forbidden = [*receipt_strings(receipts), ROOM_PLANT, WHY_RAN, WHY_ASKED]
            for turn in played.turns:
                assert turn.text in (OKAY, CHECKING.text), f"her stored turn is not her words: {turn.text!r}"
                for text in (turn.text, turn.spoken or ""):
                    assert not [s for s in forbidden if s in text]
            assert played.answer.text == OKAY
            bodies = [played.out.body, *(row.outbound.body for row in played.queued)]
            assert all(b in ("", OKAY, CHECKING.text) for b in bodies), bodies
            if not later:
                assert played.out.body == OKAY

    run(go())


@pytest.mark.parametrize("medium", ["text", "spoken"])
def test_c01_closing_returns_her_reply_as_the_model_wrote_it(medium: str) -> None:
    async def go() -> None:
        landing, _ = await held_landing(replace(WEB, medium="spoken" if medium == "spoken" else "text"))
        reply = Reply(spoken="Spoken, as written.", text="Text, as written.", worth_saying=False)
        closed = await landing.closing(reply)
        assert (closed.text, closed.spoken) == (reply.text, reply.spoken)
        assert landing.receipts is not None and landing.receipts.held

    run(go())


def test_c01_the_leak_probe_names_every_string_it_looks_for() -> None:
    shown = receipt_strings(Receipts((Receipt("Did a", "a (x: 1)", "because"),), (Receipt("Held b", "b (y: 2)", None),), 4))
    assert {OLD_DONE_INTRO, OLD_HELD_INTRO, "Did a", "a (x: 1)", "because", "Held b", "b (y: 2)"} <= set(shown)
