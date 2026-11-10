"""Contracts 2, 3 and 4: a judged change that ran is in `receipts.done` of the turn that answers, whatever her reply says
and even when its record could not be written; a runs-tier change never is."""

from ashley import services
from ashley.senses.outside_record import OutsideRecord
from outside_record_support import MemoryRecord
from contract.conversations_support import run
from ashley.inference.reply import Reply
from receipts_blind_support import (ANSWER, CHECKING, LAMP_LABEL, MAIL_LABEL, OKAY, World, change, changes, database,
                                    looked, play)
from receipts_blind_unit_support import Down, Rig


def test_c02_a_judged_change_is_shown_though_her_reply_mentions_nothing(world: World) -> None:
    async def go() -> None:
        async with database(world):
            played = await play(world, world.web(), [CHECKING, looked(), change(), ANSWER])
            receipts = played.answer.receipts
            assert played.answer.text == OKAY
            assert receipts is not None and receipts.held == () and receipts.proposal_id is None
            assert [r.headline for r in receipts.done] == [LAMP_LABEL]

    run(go())


def test_c02_a_reply_that_names_the_change_still_shows_it_once(world: World) -> None:
    said = Reply(spoken="I turned the lamp on.", text="I turned the lamp on.")

    async def go() -> None:
        async with database(world):
            played = await play(world, world.web(), [CHECKING, looked(), change(), said])
            receipts = played.answer.receipts
            assert played.answer.text == said.text
            assert receipts is not None and [r.headline for r in receipts.done] == [LAMP_LABEL]

    run(go())


def test_c02_two_judged_changes_are_two_entries_in_the_order_they_ran() -> None:
    async def go() -> None:
        rig = Rig()
        await rig.call("house_do", "c1", action="light.turn_on")
        await rig.call("mail_label", "c2", folder="archive")
        got = await rig.outside.receipts()
        assert got is not None and [r.headline for r in got.done] == [LAMP_LABEL, MAIL_LABEL]

    run(go())


def test_c02_a_turn_that_read_nothing_outside_has_no_receipts() -> None:
    async def go() -> None:
        rig = Rig(tainted=None)
        await rig.call("house_do")
        assert len(rig.source.ran) == 1 and await rig.outside.receipts() is None

    run(go())


def test_c02_a_tainted_turn_that_changed_nothing_has_no_receipts() -> None:
    async def go() -> None:
        rig = Rig()
        await rig.call("look")
        assert await rig.outside.receipts() is None

    run(go())


def test_c03_a_runs_tier_change_is_recorded_and_never_shown(world: World) -> None:
    async def go() -> None:
        async with database(world):
            played = await play(world, world.web(), [CHECKING, looked(), change("chime"), ANSWER])
            assert played.answer.receipts is None
            assert world.count("SELECT count(*) FROM outside_actions WHERE tier = 'runs'") == 1
            assert world.judge.asked == []

    run(go())


def test_c03_beside_a_judged_change_a_runs_tier_one_is_still_not_shown(world: World) -> None:
    async def go() -> None:
        async with database(world):
            played = await play(world, world.web(), [CHECKING, looked(), changes("chime", "house_do", "chime"), ANSWER])
            receipts = played.answer.receipts
            assert receipts is not None and [r.headline for r in receipts.done] == [LAMP_LABEL]
            assert world.count("SELECT count(*) FROM outside_actions WHERE tier = 'runs'") == 2

    run(go())


def test_c03_the_unit_agrees_a_runs_tier_change_is_not_in_done() -> None:
    async def go() -> None:
        rig = Rig()
        await rig.call("chime")
        assert isinstance(rig.record, MemoryRecord) and [a.tier for a in rig.record.actions] == ["runs"]
        assert await rig.outside.receipts() is None

    run(go())


def test_c04_a_judged_change_whose_record_could_not_be_written_is_still_shown() -> None:
    async def go() -> None:
        rig = Rig(record=Down())
        result = await rig.call("house_do")
        got = await rig.outside.receipts()
        assert not result.is_error and len(rig.source.ran) == 1
        assert got is not None and [r.headline for r in got.done] == [LAMP_LABEL]

    run(go())


def test_c04_the_stored_turn_holds_a_change_whose_record_could_not_be_written(world: World) -> None:
    async def go() -> None:
        async with database(world):
            services.register(OutsideRecord, Down())
            played = await play(world, world.web(), [CHECKING, looked(), change(), ANSWER])
            receipts = played.answer.receipts
            assert receipts is not None and [r.headline for r in receipts.done] == [LAMP_LABEL]
            assert len(world.first.tools.ran) == 2

    run(go())
