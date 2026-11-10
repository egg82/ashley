"""What a log line may carry: tool names only on `respond.offered`, and nothing of what landed (amount, payee, account
name) from the deposit sense, the store or a reminder's turn, while the turn itself is told them."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley import logs
from ashley.channels.respond import respond
from ashley.channels.wake.reminder_turn import inbound
from ashley.inference.model import ToolSpec
from ashley.inference.reply import Reply
from ashley.senses import deposit_sense
from ashley.channels.model import Inbound
from ashley.senses.deposit_rule import Landed
from ashley.senses.wakes import Reminder
from contract.conversations_support import events, run
from deposit_support import NOW, DepositSure, deposit, house, rule
from reminders_look_blind_support import ACCOUNT, AMOUNT_FORMS, CENTS, DAY, LANDED, PAYEE
from respond_support import ALANA, Fakes, wired as wired


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

REPLY = Reply(spoken="Move it.", text="Move it.")
SENTINELS = (PAYEE, ACCOUNT, *AMOUNT_FORMS)


def nothing_of_it(out: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in out


def test_the_sense_and_the_store_log_nothing_of_what_landed(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", CENTS, DAY, merchant=PAYEE)])
        async with house(db_url, sure) as h:
            await h.arm(rule(payee="ZQPayee", account_name=ACCOUNT))
            await deposit_sense.poll(NOW)
            await deposit_sense.poll(NOW)
            armed = await h.arm(rule(payee="ZQPayee", account_name=ACCOUNT))
            await h.deposits.fire(armed, "t-direct", LANDED)
            await h.deposits.fire(armed, "t-direct", LANDED)
            kept = [d.wake for d in await h.wakes.due(10) if isinstance(d.wake, Reminder)]
            assert len(kept) >= 2 and all(k.landed == LANDED for k in kept), "the control: the sentinels were stored"

    run(go())
    out = capsys.readouterr().out
    assert events(out, "deposits.poll"), "the control: the sense did log, so an empty search means absence"
    nothing_of_it(out)


def test_a_payee_postgres_cannot_hold_logs_nothing_of_it_either(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            try:
                await h.deposits.fire(armed, "t1", Landed(CENTS, DAY, ACCOUNT, PAYEE + "\x00"))
            except Exception:
                pass

    run(go())
    nothing_of_it(capsys.readouterr().out)


def reminder_turn(who_id: int = ALANA.id) -> Inbound:
    r = Reminder(10, who_id, who_id, "move it", datetime(2026, 11, 3, 15, tzinfo=UTC), None, LANDED)
    return inbound(31, r, ALANA, ALANA)


def prompted(wired: Fakes) -> str:
    return repr(wired.inference.prompts)


def test_the_turn_is_told_what_landed_and_no_log_line_repeats_it(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [REPLY]
    asyncio.run(respond(reminder_turn()))
    out = capsys.readouterr().out
    assert PAYEE in prompted(wired) and ACCOUNT in prompted(wired)
    assert events(out, "respond.offered"), "the control: the turn did log"
    nothing_of_it(out)


def test_offered_names_the_tools_that_read_and_only_names(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.tools.specs = (ToolSpec("lights", "the lights", {"type": "object"}, reads=True),
                         ToolSpec("lamp_on", "turn on", {"type": "object"}, reads=False),
                         ToolSpec("balance", "money", {"type": "object", "description": PAYEE}, reads=True))
    wired.inference.script = [REPLY]
    asyncio.run(respond(reminder_turn()))
    (offered,) = events(capsys.readouterr().out, "respond.offered")
    listed = set(offered["tools"].replace(",", " ").split())
    assert {"lights", "balance"} <= listed and "lamp_on" not in listed
    assert PAYEE not in offered["tools"] and "the lights" not in offered["tools"] and "turn on" not in offered["tools"]


def test_a_turn_that_is_not_reads_only_still_offers_every_tool(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.tools.specs = (ToolSpec("lights", "x", {"type": "object"}, reads=True),
                         ToolSpec("lamp_on", "x", {"type": "object"}, reads=False))
    wired.inference.script = [REPLY]
    asyncio.run(respond(replace(reminder_turn(), reads_only=False)))
    (offered,) = events(capsys.readouterr().out, "respond.offered")
    assert {"lights", "lamp_on"} <= set(offered["tools"].replace(",", " ").split())


def test_a_turn_that_does_not_reach_one_person_alone_logs_no_tools_and_calls_none(wired: Fakes,
                                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [REPLY]
    asyncio.run(respond(replace(reminder_turn(), audience="present", shared=True)))
    (offered,) = events(capsys.readouterr().out, "respond.offered")
    assert "lights" not in offered["tools"] and wired.tools.called == []


def test_the_poll_counts_a_deposit_as_fired_only_the_first_time_it_stores_one(db_url: str,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", CENTS, DAY, merchant=PAYEE)])
        async with house(db_url, sure) as h:
            await h.arm(rule(payee="ZQPayee"))
            await deposit_sense.poll(NOW)
            await deposit_sense.poll(NOW)

    run(go())
    polls = events(capsys.readouterr().out, "deposits.poll")
    assert [p["fired"] for p in polls] == ["1", "0"]
