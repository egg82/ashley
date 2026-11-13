"""Contracts 5, 6 and 7: held calls are receipts in order with the code's full summary and the proposal's id; a shared
reply shows a change by its label alone; a headline is the tool's label, else the configured `unlabelled`, never its name."""

from dataclasses import replace

from ashley import services
from ashley.channels.landing import Landing
from ashley.inference.reply import Reply
from ashley.senses.proposals import Proposals
from ashley.tools import outside_config, outside_summary
from contract.conversations_support import run
from receipts_blind_support import (ANSWER, CHECKING, LAMP_LABEL, MAIL_LABEL, WHY_ASKED, WHY_RAN, World, change, changes,
                                    database, looked, play)
from receipts_blind_unit_support import LIMITS, WEB, Numbered, Rig, held_landing


def test_c05_held_calls_are_receipts_in_order_with_the_summary_in_full_and_the_proposals_id() -> None:
    async def go() -> None:
        rig = Rig(judge=None)
        rig.judge.answers = {"house_do": "ask", "mail_label": "ask"}
        await rig.call("house_do", "c1", action="light.turn_on", room="porch")
        await rig.call("mail_label", "c2", folder="archive", subject="a long subject")
        got = await rig.outside.receipts()
        held = (await rig.proposal()).payload.calls
        assert got is not None and got.done == ()
        assert [r.detail for r in got.held] == [h.summary for h in held] and len(held) == 2
        assert [r.headline for r in got.held] == [LAMP_LABEL, MAIL_LABEL]
        assert got.proposal_id == (await rig.proposal()).id and got.proposal_id is not None
        assert rig.outside.agree == got.proposal_id and rig.outside.held == 2

    run(go())


def test_c05_the_judges_reason_is_the_receipts_why() -> None:
    async def go() -> None:
        rig = Rig()
        rig.judge.answers = {"mail_label": "ask"}
        await rig.call("house_do", "c1")
        await rig.call("mail_label", "c2", folder="archive")
        got = await rig.outside.receipts()
        assert got is not None
        assert [r.why for r in got.done] == [WHY_RAN] and [r.why for r in got.held] == [WHY_ASKED]

    run(go())


def test_c05_done_and_held_in_one_turn_are_both_shown_with_the_proposal_only_for_held() -> None:
    async def go() -> None:
        rig = Rig()
        rig.judge.answers = {"mail_label": "ask"}
        await rig.call("house_do", "c1")
        await rig.call("mail_label", "c2", folder="archive")
        got = await rig.outside.receipts()
        assert got is not None and (len(got.done), len(got.held)) == (1, 1) and got.proposal_id is not None

    run(go())


def test_c05_a_turn_that_did_and_held_nothing_has_none() -> None:
    async def go() -> None:
        rig = Rig()
        assert await rig.outside.receipts() is None
        assert (rig.outside.held, rig.outside.agree) == (0, None)

    run(go())


def test_c05_a_held_turn_is_worth_saying_whatever_she_set_and_a_done_only_one_is_not_made_so() -> None:
    async def go() -> None:
        landing, number = await held_landing(WEB)
        closed = await landing.closing(Reply(spoken="s", text="I looked.", says="none"))
        assert closed.says == "reply" and landing.held == 2 and landing.agree == number
        assert landing.receipts is not None and landing.receipts.proposal_id == number
        assert [r.detail for r in landing.receipts.held] == ['lamp (room: "porch")', "garage (door: 2)"]

    run(go())


def test_c05_a_turn_that_held_nothing_closes_as_she_said_it_with_no_receipts() -> None:
    async def go() -> None:
        services.register(Proposals, Numbered())
        landing = Landing(replace(WEB, taint="watch"), (40, 100), LIMITS)
        reply = Reply(spoken="s", text="hello", says="none")
        assert await landing.closing(reply) == reply and landing.receipts is None and landing.held == 0

    run(go())


def test_c05_the_stored_snapshot_has_the_held_calls_in_order_and_their_proposal(world: World) -> None:
    world.judge.answers = {"house_do": "ask", "mail_label": "ask"}

    async def go() -> None:
        async with database(world):
            played = await play(world, world.web(), [CHECKING, looked(), changes("house_do", "mail_label"), ANSWER])
            receipts = played.answer.receipts
            assert receipts is not None and receipts.done == () and len(receipts.held) == 2
            assert [r.headline for r in receipts.held] == [LAMP_LABEL, MAIL_LABEL]
            proposal = world.count("SELECT id FROM proposals ORDER BY id DESC LIMIT 1")
            assert receipts.proposal_id == proposal
            assert world.first.tools.ran[1:] == [], "nothing held was run"

    run(go())


def test_c06_a_shared_reply_shows_a_change_by_its_label_alone() -> None:
    async def go() -> None:
        rig = Rig(private=False)
        await rig.call("house_do")
        got = await rig.outside.receipts()
        assert got is not None and [(r.headline, r.detail) for r in got.done] == [(LAMP_LABEL, None)]

    run(go())


def test_c06_a_private_reply_adds_the_codes_summary_as_detail() -> None:
    async def go() -> None:
        rig = Rig(private=True)
        await rig.call("house_do", "c1", action="light.turn_on", room="porch")
        got = await rig.outside.receipts()
        named = outside_config.load().summary_arguments["house_do"]
        expected = outside_summary.done_summary(LAMP_LABEL, {"action": "light.turn_on", "room": "porch"}, named)
        assert got is not None and [r.detail for r in got.done] == [expected]
        assert "porch" not in (got.done[0].detail or "")

    run(go())


def test_c06_in_a_shared_channel_the_stored_receipt_has_no_detail(world: World) -> None:
    async def go() -> None:
        async with database(world):
            played = await play(world, world.discord(shared=True), [CHECKING, looked(), change(), ANSWER])
            receipts = played.answer.receipts
            assert receipts is not None and [(r.headline, r.detail) for r in receipts.done] == [(LAMP_LABEL, None)]

    run(go())


def test_c07_a_headline_is_the_label_else_unlabelled_and_never_the_tool_name() -> None:
    async def go() -> None:
        rig = Rig()
        rig.judge.answers = {"mystery_change": "ask"}
        await rig.call("house_do", "c1")
        await rig.call("mystery_change", "c2")
        got = await rig.outside.receipts()
        assert got is not None
        assert [r.headline for r in got.done] == [LAMP_LABEL]
        assert [r.headline for r in got.held] == [outside_config.load().unlabelled]
        assert all(r.headline not in ("house_do", "mystery_change") for r in (*got.done, *got.held))

    run(go())


def test_c07_an_unlabelled_change_that_ran_is_headed_unlabelled() -> None:
    async def go() -> None:
        rig = Rig()
        await rig.call("mystery_change")
        got = await rig.outside.receipts()
        assert got is not None and [r.headline for r in got.done] == [outside_config.load().unlabelled]

    run(go())
