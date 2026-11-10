"""Contract 10, voice: nothing code wrote is spoken or sent as her reply; a voice turn with receipts and a speaker the
phone can reach queues exactly one receipt-only push with the turn (none extra when her `to_phone` copy carries them);
an unreachable speaker queues none and the turn logs `receipts.unshown` once. Other channels queue no extra push."""

import pytest
from ashley.channels.outbox import Later
from ashley.channels.push import config as push_config
from ashley.inference.reply import Reply
from contract.conversations_support import run
from later_support import Logged
from receipts_blind_support import (ANSWER, CHECKING, LAMP_LABEL, OKAY, Played, World, change, database, looked, notified,
                                    play)

PHONE_ANSWER = Reply(spoken=OKAY, text=OKAY, to_phone=True)


def pushes(played: Played) -> list[Later]:
    return [row for row in played.queued if row.thread.startswith("push:")]


def test_c10_the_reply_of_a_voice_turn_carries_receipts_beside_her_words_not_in_them(world: World) -> None:
    async def go() -> None:
        async with database(world):
            played = await play(world, world.voice(), [looked(), change(), ANSWER])
            assert played.out.body == OKAY and played.answer.text == OKAY
            assert played.out.receipts is not None and played.out.receipts == played.answer.receipts
            assert [r.headline for r in played.out.receipts.done] == [LAMP_LABEL]

    run(go())


def test_c10_a_reachable_speaker_gets_exactly_one_receipt_only_push_queued_with_the_turn(world: World) -> None:
    world.phone()

    async def go() -> None:
        async with database(world):
            played = await play(world, world.voice(), [looked(), change(), ANSWER])
            rows = pushes(played)
            assert len(rows) == 1 and rows[0].thread == f"push:{world.who.id}"
            assert rows[0].outbound.body == "" and rows[0].outbound.receipts == played.answer.receipts
            assert len(played.queued) == 1, "no other reply is queued for a voice turn"
            (note,) = await notified(rows[0])
            assert LAMP_LABEL in note.body and note.agree is None
            assert note.title == push_config.load().done_title

    run(go())


def test_c10_a_held_change_pushes_with_agree_on_the_one_notification(world: World) -> None:
    world.phone()
    world.judge.answers = {"house_do": "ask"}

    async def go() -> None:
        async with database(world):
            played = await play(world, world.voice(), [looked(), change(), ANSWER])
            receipts = played.answer.receipts
            (row,) = pushes(played)
            assert receipts is not None and receipts.proposal_id is not None and receipts.held
            (note,) = await notified(row)
            assert note.agree == receipts.proposal_id and receipts.held[0].detail
            assert note.title == push_config.load().held_title
            assert OKAY not in note.body, "her words are spoken, not pushed, when she chose no phone copy"

    run(go())


@pytest.mark.parametrize("held", [False, True])
def test_c10_when_she_sends_the_phone_copy_it_carries_the_receipts_and_nothing_else_is_queued(
        world: World, held: bool) -> None:
    world.phone()
    if held:
        world.judge.answers = {"house_do": "ask"}

    async def go() -> None:
        async with database(world):
            played = await play(world, world.voice(), [looked(), change(), PHONE_ANSWER])
            (row,) = pushes(played)
            assert len(played.queued) == 1
            assert row.outbound.body == OKAY and row.outbound.receipts == played.answer.receipts
            notes = await notified(row)
            assert len(notes) == 1 and notes[0].body == OKAY
            expected = played.answer.receipts.proposal_id if held and played.answer.receipts else None
            assert notes[0].agree == expected

    run(go())


def test_c10_an_unreachable_speaker_queues_no_push_and_the_turn_logs_unshown_once(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)

    async def go() -> None:
        async with database(world):
            played = await play(world, world.voice(), [looked(), change(), ANSWER])
            assert played.queued == [] and played.answer.receipts is not None

    run(go())
    (line,) = log.events("receipts.unshown")
    assert line["done"] == "1" and line["held"] == "0" and line["medium"] == "spoken"
    assert set(line) >= {"conversation", "medium", "done", "held"}


def test_c10_a_voice_turn_with_nothing_to_show_pushes_and_logs_nothing(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.phone()
    log = Logged(capsys)

    async def go() -> None:
        async with database(world):
            played = await play(world, world.voice(), [ANSWER])
            assert played.queued == [] and played.answer.receipts is None

    run(go())
    assert log.events("receipts.unshown") == []


@pytest.mark.parametrize("channel", ["web", "discord"])
def test_c10_a_page_or_a_discord_turn_queues_no_receipt_push_though_the_phone_is_reachable(
        world: World, channel: str) -> None:
    world.phone()

    async def go() -> None:
        async with database(world):
            inbound = world.web() if channel == "web" else world.discord()
            played = await play(world, inbound, [CHECKING, looked(), change(), ANSWER])
            assert pushes(played) == []
            assert played.answer.receipts is not None

    run(go())
