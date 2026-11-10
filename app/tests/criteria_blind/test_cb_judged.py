"""A fired reminder she judges: its turn is not promised and her `worth_saying` decides whether the phone is told; one she
does not judge is promised and goes out whatever she answers. The turn carries what the transaction was."""

from datetime import UTC, date, datetime, timedelta

import pytest
from ashley import logs
from ashley.channels.wake import runner
from ashley.channels.wake.reminder_turn import inbound, said
from ashley.criteria.predicates import History
from ashley.criteria.record import Direction
from ashley.inference.reply import Reply
from ashley.people.model import Person
from ashley.senses.deposit_rule import Landed
from ashley.senses.wakes import Reminder
from contract.conversations_support import run
from contract.test_inflight_resume import World
from cb_judged_support import Stack, stack
from ashley.db.pool import PoolDatabase
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.postgres_deposits import PostgresDeposits
from money_support import CHECKING

DONE = Reply(spoken="Time to move it.", text="Time to move it.")
QUIET = Reply(spoken="Nothing to say.", text="Nothing to say.", worth_saying=False)
LOUD = Reply(spoken="Move it.", text="Move it.", worth_saying=True)
ALANA = Person(3, 1, "Alana")
DAY = date(2026, 11, 3)
HISTORY = History(4, 100_000, 123_400, 30, date(2026, 10, 4))


def landed(judged: bool, direction: Direction = "in") -> Landed:
    return Landed(456_700, DAY, "Joint Checking", "KVR Payroll", direction, ("payee", "amount_vs_usual"), HISTORY, judged)


def fires(who: Person, judged: bool, direction: Direction = "in") -> Reminder:
    return Reminder(who.household_id, who.id, who.id, "Move the bonus to savings.", datetime.now(UTC) - timedelta(seconds=5), None,
                    landed(judged, direction))


async def fire(s: Stack, judged: bool) -> None:
    """Arm a rule for Alana and fire it for a transaction, as the sense does: the reminder is stored due now with `landed`."""
    db = PoolDatabase(s.world.url, connect_timeout_s=5.0)
    await db.open()
    try:
        deposits = PostgresDeposits(db)
        base = Reminder(s.house, s.alana, s.alana, "Move the bonus to savings.", datetime.now(UTC) - timedelta(days=1), None)
        armed = await deposits.arm(base, DepositRule(CHECKING, "Joint Checking", 1_000))
        assert await deposits.fire(armed, "tx-1", landed(judged))
    finally:
        await db.close()


def test_a_judged_fire_is_not_promised_and_an_unjudged_one_is() -> None:
    assert inbound(1, fires(ALANA, True), ALANA, ALANA).promised is False
    assert inbound(1, fires(ALANA, False), ALANA, ALANA).promised is True
    plain = Reminder(1, 3, 3, "pay the Visa", datetime.now(UTC), None)
    assert inbound(1, plain, ALANA, ALANA).promised is True


def test_the_fire_is_still_hers_alone_and_unprompted_whether_or_not_it_is_judged() -> None:
    for judged in (True, False):
        got = inbound(1, fires(ALANA, judged), ALANA, ALANA)
        assert got.unprompted is True


def test_her_turn_is_handed_the_figures_the_reason_and_the_payers_history() -> None:
    text = said(fires(ALANA, True), ALANA, ALANA)
    for part in ("4,567.00", "KVR Payroll", "Joint Checking", "1,000.00", "1,234.00", "Move the bonus to savings."):
        assert part in text or part.replace(",", "") in text, part
    assert "2026-11-03" in text or "November 3" in text or "Nov 3" in text
    assert "4" in text


def test_only_a_judged_turn_tells_her_she_may_stay_quiet() -> None:
    assert "worth_saying" in said(fires(ALANA, True), ALANA, ALANA)
    assert "worth_saying" not in said(fires(ALANA, False), ALANA, ALANA)


def test_a_withdrawal_is_told_as_one() -> None:
    text = said(fires(ALANA, False, "out"), ALANA, ALANA).lower()
    assert "withdrawal" in text
    assert "withdrawal" not in said(fires(ALANA, False), ALANA, ALANA).lower()


@pytest.mark.parametrize("judged,reply,sent", [(True, QUIET, 0), (True, LOUD, 1), (True, DONE, 1), (False, QUIET, 1),
                                                (False, LOUD, 1)])
def test_a_judged_fire_goes_out_only_when_she_says_it_is_worth_it(world: World, judged: bool, reply: Reply, sent: int) -> None:
    world.first.inference.script = [reply]

    async def go() -> None:
        async with stack(world) as s:
            await fire(s, judged)
            assert await runner.sweep() >= 1
            assert await s.deliver() == 1
            assert len(s.sender.sent) == sent
            assert await s.deliver() == 0       # settled either way: a kept-quiet fire is not tried again
            assert len(s.sender.sent) == sent

    run(go())


def test_a_fire_she_kept_quiet_is_logged_as_kept_quiet_and_not_as_undelivered(world: World,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    world.first.inference.script = [QUIET]

    async def go() -> None:
        async with stack(world) as s:
            await fire(s, True)
            await runner.sweep()
            await s.deliver()
            assert s.sender.sent == []
            assert all(r.state != "undelivered" for r in await s.wakes.reminders(s.house, s.alana))

    run(go())
    seen = capsys.readouterr()
    text = seen.out + seen.err
    assert "push.reminder" in text and "outcome=kept_quiet" in text
    for private in ("4567", "KVR Payroll", "Joint Checking", "Nothing to say", "Move the bonus"):
        assert private not in text, private


def test_a_fire_that_went_out_is_not_logged_as_kept_quiet(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    world.first.inference.script = [LOUD]

    async def go() -> None:
        async with stack(world) as s:
            await fire(s, True)
            await runner.sweep()
            await s.deliver()
            assert len(s.sender.sent) == 1

    run(go())
    seen = capsys.readouterr()
    assert "kept_quiet" not in seen.out + seen.err
