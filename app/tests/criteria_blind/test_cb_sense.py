"""The deposit sense with conditions on a real database: the payer's history is read in code and judged against, the
fired reminder carries why it fired, and what is not income into the account is not history."""

import pytest
from datetime import timedelta

from ashley.senses.deposit_rule import DepositRule
from cb_sense_support import TODAY, new_row, payer_rows, polled
from criteria_blind_support import above, amount, below, new_payer, off_day, payee, rule
from money_support import CHECKING


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

ALANA = rule((payee("KVR"), above(20)), (payee("KVR"), off_day(3)), (new_payer(2),))
PAYROLL = payer_rows("KVR", 100_000, 30, 60, 90, 120)


def test_the_usual_paycheck_on_its_usual_day_does_not_fire_and_what_came_before_it_never_does(db_url: str) -> None:
    got = polled(db_url, [*PAYROLL, new_row(100_000)], ALANA)
    assert got.landed == []


def test_an_unusually_large_paycheck_fires_and_says_why_with_the_history_it_was_judged_against(db_url: str) -> None:
    (got,) = polled(db_url, [*PAYROLL, new_row(400_000)], ALANA).landed
    assert got.cents == 400_000 and got.day == TODAY and got.payee == "KVR" and got.because == ("payee", "amount_vs_usual")
    assert got.history is not None and (got.history.seen, got.history.low_cents, got.history.high_cents) == (4, 100_000, 100_000)
    assert got.history.last_day == TODAY - timedelta(days=30) and got.judged is False




def test_a_paycheck_off_its_usual_day_fires_on_the_day_clause(db_url: str) -> None:
    late = [*payer_rows("KVR", 100_000, 38, 68, 98, 128), new_row(100_000)]
    (got,) = polled(db_url, late, ALANA).landed
    assert got.because == ("payee", "day_vs_usual")


def test_a_payer_new_to_the_account_fires_even_with_no_payee_or_amount_to_name(db_url: str) -> None:
    (got,) = polled(db_url, [*PAYROLL, new_row(250_000, "FPX Payout")], ALANA).landed
    assert got.because == ("payee_new",) and got.payee == "FPX Payout"
    assert got.history is not None and got.history.seen == 0


def test_a_payer_seen_twice_is_not_new(db_url: str) -> None:
    assert polled(db_url, [*payer_rows("FPX", 5, 40, 80), new_row(5, "FPX")], rule((new_payer(2),))).landed == []


def test_a_payer_seen_once_is_new_until_twice(db_url: str) -> None:
    assert len(polled(db_url, [*payer_rows("FPX", 5, 40), new_row(5, "FPX")], rule((new_payer(2),))).landed) == 1


def test_transfers_in_from_the_payers_name_are_not_its_history(db_url: str) -> None:
    rows = [*payer_rows("FPX", 5, 40, 80, 100, transfer=True), new_row(5, "FPX")]
    assert len(polled(db_url, rows, rule((new_payer(2),))).landed) == 1


def test_deposits_into_another_account_and_the_other_direction_are_not_the_payers_history(db_url: str) -> None:
    rows = [*payer_rows("FPX", 5, 40, 80, account_id="elsewhere"), *payer_rows("FPX", 5, 50, 70, ids="x", classification="expense"),
            new_row(5, "FPX")]
    assert len(polled(db_url, rows, rule((new_payer(2),))).landed) == 1


def test_history_older_than_the_lookback_of_the_predicate_is_not_counted(db_url: str) -> None:
    rows = [*payer_rows("FPX", 5, 60, 80), new_row(5, "FPX")]
    assert len(polled(db_url, rows, rule((new_payer(2, days=30),))).landed) == 1


def test_history_inside_the_lookback_of_the_predicate_is_counted(db_url: str) -> None:
    rows = [*payer_rows("FPX", 5, 60, 80), new_row(5, "FPX")]
    assert polled(db_url, rows, rule((new_payer(2, days=150),))).landed == []


def test_the_sense_reads_as_far_back_as_the_conditions_ask(db_url: str) -> None:
    deep = polled(db_url, [new_row(5)], rule((payee("KVR"), above(20, days=200))))
    assert min(deep.starts) <= str(TODAY - timedelta(days=200))


def test_the_sense_reads_no_further_back_when_no_condition_reads_history(db_url: str) -> None:
    plain = polled(db_url, [new_row(5)], rule((payee("KVR"), amount(lo=1))))
    assert min(plain.starts) > str(TODAY - timedelta(days=30))


def test_a_judged_rule_reads_the_judged_days_and_carries_the_history_and_the_judged_flag(db_url: str) -> None:
    rows = [*payer_rows("KVR", 100_000, 30, 100, 150), new_row(400_000)]
    got = polled(db_url, rows, rule((payee("KVR"),), judge=True))
    assert min(got.starts) <= str(TODAY - timedelta(days=120))
    (landed,) = got.landed
    assert landed.judged is True and landed.because == ("payee",)
    assert landed.history is not None and landed.history.seen == 2 and landed.history.high_cents == 100_000


def test_a_judged_rule_with_only_a_minimum_also_lands_with_history(db_url: str) -> None:
    (landed,) = polled(db_url, [*payer_rows("KVR", 100_000, 30), new_row(400_000)], rule(min_cents=200_000, judge=True)).landed
    assert landed.judged is True and landed.history is not None and landed.history.seen == 1


def test_a_withdrawal_rule_judges_against_the_payees_earlier_withdrawals(db_url: str) -> None:
    rows = [*payer_rows("Statewide Mutual", 10_000, 30, 60, 90, classification="expense"),
            *payer_rows("Statewide Mutual", 900_000, 20, ids="x"), new_row(25_000, "Statewide Mutual", classification="expense")]
    (got,) = polled(db_url, rows, rule((payee("Statewide Mutual"), above(50)), direction="out")).landed
    assert got.direction == "out" and got.because == ("payee", "amount_vs_usual")
    assert got.history is not None and got.history.high_cents == 10_000


def test_below_the_smallest_fires_too(db_url: str) -> None:
    (got,) = polled(db_url, [*PAYROLL, new_row(40_000)], rule((payee("KVR"), below(30)))).landed
    assert got.because == ("payee", "amount_vs_usual")


def test_polling_again_fires_it_once_and_the_history_is_the_same_each_time(db_url: str) -> None:
    got = polled(db_url, [*PAYROLL, new_row(400_000)], ALANA, polls=3)
    assert len(got.landed) == 1


def test_the_old_fields_still_decide_alone(db_url: str) -> None:
    r = DepositRule(CHECKING, "Checking", 200_000, "KVR")
    got = polled(db_url, [*PAYROLL, new_row(400_000), new_row(5, id_="small")], r)
    assert [x.cents for x in got.landed] == [400_000] and got.landed[0].because == () and got.landed[0].history is None
