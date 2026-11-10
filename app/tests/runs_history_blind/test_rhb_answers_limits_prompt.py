"""`answers.answer_of`, `limits.parse` and `prompt.messages`."""

import json
from typing import Any

import pytest
from ashley.channels import limits as limits_module
from ashley.channels.prompt import messages
from ashley.conversations.answers import answer_of
from ashley.conversations.model import Turn
from ashley.people.model import Household, Person
from rhb_support import T0, turn

KIND_ENTRY: dict[str, Any] = {"max_tool_rounds": 1, "max_tool_result_chars": 10, "recent_turns": 1,
                              "relevant_turns": 0, "hold_after_s": 1, "deadline_s": 2, "carried_runs": 2,
                              "run_script_chars": 30, "run_output_chars": 40}


def P(i: int) -> Turn:
    return turn(i, "person")


def A(i: int, answers: int | None = None, follows: bool = False) -> Turn:
    return turn(i, "ashley", follows, answers=answers)


def test_a_person_turn_is_answered_by_the_last_of_hers_recording_it() -> None:
    assert answer_of([P(1), A(2, 1), A(3, 1), P(4), A(5, 4)]) == {1: 3, 4: 5}


def test_a_person_turn_with_nothing_of_hers_after_it_has_no_entry() -> None:
    assert answer_of([P(1), A(2, 1), P(3)]) == {1: 2}
    assert answer_of([P(1)]) == {}
    assert answer_of([]) == {}


def test_a_trailing_held_line_is_not_yet_an_answer() -> None:
    assert answer_of([P(1), A(2, 1, follows=True)]) == {}
    assert answer_of([P(1), A(2, 1), P(3), A(4, 3, follows=True)]) == {1: 2}


def test_a_held_line_followed_by_its_answer_is_answered_by_the_answer() -> None:
    assert answer_of([P(1), A(2, 1, follows=True), A(3, 1)]) == {1: 3}


def test_a_held_line_is_no_answer_even_when_a_person_turn_follows_it() -> None:
    assert answer_of([P(1), A(2, 1, follows=True), P(3)]) == {}


def test_consecutive_person_turns_are_answered_by_the_last_asking_only() -> None:
    assert answer_of([P(1), P(2), A(3, 2)]) == {2: 3}


def test_hers_before_any_person_turn_answers_nothing() -> None:
    assert answer_of([A(1, None), P(2), A(3, 2)]) == {2: 3}


def test_limits_parse_reads_the_three_run_budgets() -> None:
    parsed = limits_module.parse({k: KIND_ENTRY for k in limits_module.KINDS})
    for entry in parsed.values():
        assert (entry.carried_runs, entry.run_script_chars, entry.run_output_chars) == (2, 30, 40)


def test_each_kind_keeps_its_own_run_budgets() -> None:
    data = {k: dict(KIND_ENTRY, carried_runs=i + 1, run_script_chars=10 * (i + 1), run_output_chars=100 * (i + 1))
            for i, k in enumerate(limits_module.KINDS)}
    for i, kind in enumerate(limits_module.KINDS):
        got = limits_module.parse(data)[kind]
        assert (got.carried_runs, got.run_script_chars, got.run_output_chars) == (i + 1, 10 * (i + 1), 100 * (i + 1))


@pytest.mark.parametrize("name", ["carried_runs", "run_script_chars", "run_output_chars"])
def test_each_run_budget_is_required(name: str) -> None:
    entry = {k: v for k, v in KIND_ENTRY.items() if k != name}
    with pytest.raises(ValueError):
        limits_module.parse({k: entry for k in limits_module.KINDS})


@pytest.mark.parametrize("name", ["carried_runs", "run_script_chars", "run_output_chars"])
@pytest.mark.parametrize("bad", [-1, 1.5, "3", True, None])
def test_a_run_budget_must_be_a_non_negative_integer(name: str, bad: object) -> None:
    with pytest.raises(ValueError):
        limits_module.parse({k: dict(KIND_ENTRY, **{name: bad}) for k in limits_module.KINDS})


@pytest.mark.parametrize("name", ["carried_runs", "run_script_chars", "run_output_chars"])
def test_zero_is_a_valid_run_budget(name: str) -> None:
    parsed = limits_module.parse({k: dict(KIND_ENTRY, **{name: 0}) for k in limits_module.KINDS})
    assert getattr(parsed["chat"], name) == 0


def test_the_shipped_limits_carry_runs_in_chat() -> None:
    chat = limits_module.load()["chat"]
    assert chat.carried_runs > 0 and chat.run_script_chars > 0 and chat.run_output_chars > 0
    for kind in limits_module.KINDS:
        assert set(json.loads(json.dumps(KIND_ENTRY))) >= {"carried_runs"}
        assert limits_module.load()[kind].carried_runs >= 0


HOME = Household(1, "home", "America/Denver", "", (Person(7, 1, "Alana"),))


def test_a_carried_turn_with_runs_ends_with_their_text_on_a_line_of_its_own() -> None:
    carried = [P(1), A(2), P(3), A(4)]
    said = turn(9, "person")
    plain = messages(carried, said, HOME)
    withruns = messages(carried, said, HOME, {2: "[code run: x]\n[end code run]"})
    assert len(withruns) == len(plain)
    assert withruns[1].text.startswith(plain[1].text)
    assert withruns[1].text.endswith("\n[code run: x]\n[end code run]")
    assert [m.text for i, m in enumerate(withruns) if i != 1] == [m.text for i, m in enumerate(plain) if i != 1]
    assert withruns[1].author == "ashley"


def test_runs_none_or_empty_changes_nothing() -> None:
    carried = [P(1), A(2)]
    said = turn(9, "person")
    assert messages(carried, said, HOME, {}) == messages(carried, said, HOME) == messages(carried, said, HOME, None)


def test_text_for_an_id_not_carried_is_ignored() -> None:
    carried = [P(1), A(2)]
    said = turn(9, "person")
    assert messages(carried, said, HOME, {55: "STRAY"}) == messages(carried, said, HOME)


def test_the_message_being_answered_gets_no_runs() -> None:
    said = turn(9, "person")
    assert messages([P(1), A(2)], said, HOME, {9: "STRAY"})[-1].text == messages([P(1), A(2)], said, HOME)[-1].text


def test_runs_go_to_the_turn_with_that_id_only_and_each_to_its_own() -> None:
    carried = [P(1), A(2), P(3), A(4)]
    got = messages(carried, turn(9, "person"), HOME, {2: "ONE", 4: "TWO"})
    assert got[1].text.endswith("\nONE") and "TWO" not in got[1].text
    assert got[3].text.endswith("\nTWO") and "ONE" not in got[3].text
    assert "ONE" not in got[0].text + got[2].text + got[4].text
    assert T0 is not None
