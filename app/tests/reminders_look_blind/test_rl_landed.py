"""`Landed`, the deposit a reminder fired for: made from a rule and a deposit, kept as JSON that reads back as the same
fields, refused with ValueError when what is read is not what `landed_to_json` makes; and `reminder_turn.said` states
it from those fields, naming nothing when there is none."""

import json
from dataclasses import replace
from datetime import date

import pytest
from ashley.channels.wake.reminder_turn import said
from ashley.senses.deposit_rule import Deposit, DepositRule, Landed, landed, landed_from_json, landed_to_json
from reminders_look_blind_support import ACCOUNT, ALANA, AMOUNT_FORMS, BRIEF, CENTS, DAY, LANDED, PAYEE, SAM, reminder

RULE = DepositRule("acct-1", ACCOUNT, 100_000, "Acme", "contains")


def deposit(names: tuple[str, ...] = (PAYEE, "ACH CREDIT 4411"), cents: int = CENTS, day: date = DAY) -> Deposit:
    return Deposit("t-1", day, "acct-1", cents, True, names)


HOSTILE = ["O'Brien & \"Sons\" <b>", "line one\nline two\r\n", "日本語の支払人 🎉", "x" * 5000, '{"cents": 1}', "'; DROP TABLE wakes;--",
           "tab\there", "{0} {payee} %s %(x)s ${HOME}", "‮evil", " ", "back\\slash\\"]


def test_it_is_made_from_the_rule_and_the_deposit() -> None:
    assert landed(RULE, deposit()) == Landed(CENTS, DAY, ACCOUNT, PAYEE)


def test_the_payee_is_the_first_name_sure_gives_and_none_when_it_gives_none() -> None:
    assert landed(RULE, deposit((PAYEE, "other"))).payee == PAYEE
    assert landed(RULE, deposit(("name only",))).payee == "name only"
    assert landed(RULE, deposit(())).payee is None


def test_the_account_name_is_the_rules_not_the_deposits_account_id() -> None:
    got = landed(replace(RULE, account_name="Joint Checking"), deposit())
    assert got.account_name == "Joint Checking"


@pytest.mark.parametrize("cents", [0, 1, 99, 100_000, 10**12])
def test_the_amount_and_day_are_the_deposits(cents: int) -> None:
    got = landed(RULE, deposit(cents=cents, day=date(2026, 1, 31)))
    assert (got.cents, got.day) == (cents, date(2026, 1, 31))


def test_json_is_plain_data_that_survives_a_text_round_trip() -> None:
    raw = landed_to_json(LANDED)
    assert isinstance(raw, dict)
    assert landed_from_json(json.loads(json.dumps(raw))) == LANDED


@pytest.mark.parametrize("payee", [None, "", *HOSTILE])
@pytest.mark.parametrize("account", ["Checking", "", *HOSTILE[:4]])
def test_whatever_the_names_the_round_trip_returns_the_same_fields(payee: str | None, account: str) -> None:
    want = Landed(1234, date(2026, 2, 28), account, payee)
    assert landed_from_json(json.loads(json.dumps(landed_to_json(want)))) == want


@pytest.mark.parametrize("cents,day", [(0, date(2026, 1, 1)), (10**15, date(2026, 12, 31)), (1, date(2024, 2, 29)),
                                       (7, date.min), (7, date.max)])
def test_the_extremes_of_amount_and_day_round_trip(cents: int, day: date) -> None:
    want = Landed(cents, day, "A", None)
    assert landed_from_json(json.loads(json.dumps(landed_to_json(want)))) == want


def test_a_missing_payee_is_a_none_payee_in_the_round_trip() -> None:
    want = replace(LANDED, payee=None)
    got = landed_from_json(json.loads(json.dumps(landed_to_json(want))))
    assert got.payee is None and got == want


@pytest.mark.parametrize("key", ["cents", "day", "account_name"])
def test_a_stored_value_missing_a_field_is_a_value_error(key: str) -> None:
    raw = dict(landed_to_json(LANDED))
    assert key in raw
    del raw[key]
    with pytest.raises(ValueError):
        landed_from_json(raw)


@pytest.mark.parametrize("key,bad", [
    ("cents", "5"), ("cents", None), ("cents", True), ("cents", 1.5), ("cents", [1]), ("cents", {}),
    ("day", "not-a-date"), ("day", "2026-13-40"), ("day", ""), ("day", None), ("day", 20261103), ("day", ["2026-11-03"]),
    ("account_name", None), ("account_name", 5), ("account_name", ["x"]),
    ("payee", 5), ("payee", ["x"]), ("payee", {"a": 1}), ("payee", True)])
def test_a_field_of_the_wrong_kind_is_a_value_error_not_another_exception(key: str, bad: object) -> None:
    raw = dict(landed_to_json(LANDED))
    raw[key] = bad
    with pytest.raises(ValueError):
        landed_from_json(raw)


@pytest.mark.parametrize("raw", [{}, {"cents": 1}, {"unrelated": "x"}])
def test_an_empty_or_foreign_mapping_is_a_value_error(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        landed_from_json(raw)


def test_what_it_makes_is_not_changed_by_reading_it_back_and_making_it_again() -> None:
    once = landed_to_json(LANDED)
    assert landed_to_json(landed_from_json(once)) == once


def stated(landed: Landed | None = LANDED) -> str:
    return said(reminder(landed), ALANA, ALANA)


def mentions_amount(text: str) -> bool:
    return any(form in text for form in AMOUNT_FORMS)


def test_she_is_told_the_amount_day_account_and_payee_of_what_landed() -> None:
    text = stated()
    assert mentions_amount(text) and DAY.isoformat() in text and ACCOUNT in text and PAYEE in text
    assert BRIEF in text


def test_without_a_deposit_nothing_of_one_is_stated() -> None:
    text = stated(landed=None)
    assert BRIEF in text
    assert not mentions_amount(text) and PAYEE not in text and ACCOUNT not in text and DAY.isoformat() not in text


def test_a_deposit_with_no_payee_states_the_rest_and_never_the_word_none() -> None:
    text = stated(landed=replace(LANDED, payee=None))
    assert mentions_amount(text) and ACCOUNT in text and DAY.isoformat() in text
    assert "None" not in text and "null" not in text.lower()


def test_what_is_stated_follows_the_fields_it_was_given() -> None:
    a = stated(landed=Landed(111_11, date(2026, 3, 1), "AcctOne", "PayerOne"))
    b = stated(landed=Landed(222_22, date(2026, 4, 2), "AcctTwo", "PayerTwo"))
    assert "111.11" in a.replace(",", "") and "2026-03-01" in a and "AcctOne" in a and "PayerOne" in a
    assert "222.22" in b.replace(",", "") and "2026-04-02" in b and "AcctTwo" in b and "PayerTwo" in b
    assert "AcctTwo" not in a and "PayerOne" not in b


@pytest.mark.parametrize("payee", [None, "", *HOSTILE])
def test_whatever_the_payee_says_the_reminder_is_still_worded_with_its_brief(payee: str | None) -> None:
    text = stated(landed=replace(LANDED, payee=payee))
    assert BRIEF in text and ACCOUNT in text


def test_the_text_for_a_person_who_was_not_the_asker_still_carries_the_deposit() -> None:
    text = said(reminder(who=SAM), SAM, ALANA)
    assert PAYEE in text and BRIEF in text


@pytest.mark.parametrize("cents,shown", [(5, "0.05"), (1205, "12.05"), (100, "1.00"), (1999, "19.99"), (0, "0.00")])
def test_the_amount_is_stated_in_dollars_and_cents(cents: int, shown: str) -> None:
    assert shown in stated(landed=replace(LANDED, cents=cents)).replace(",", "")


def test_a_stored_value_with_a_field_that_landed_never_has_is_a_value_error() -> None:
    raw = dict(landed_to_json(LANDED))
    raw["amount"] = "1.00"
    with pytest.raises(ValueError):
        landed_from_json(raw)


def test_a_stored_value_without_its_payee_key_is_a_value_error() -> None:
    raw = dict(landed_to_json(replace(LANDED, payee=None)))
    del raw["payee"]
    with pytest.raises(ValueError):
        landed_from_json(raw)
