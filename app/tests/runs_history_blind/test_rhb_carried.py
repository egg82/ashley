"""`history_runs.carried`: which runs go under which carried answer, from one read."""

import logging
from collections.abc import Coroutine
from typing import Any

import pytest
from ashley import services
from ashley.channels.history_runs import block, carried
from ashley.runs.model import Run
from ashley.runs.runs import Runs
from rhb_support import CountingRuns, limits, out, stored, turn
from contract.conversations_support import run


def go(coro: Coroutine[Any, Any, dict[int, str]]) -> dict[int, str]:
    result: dict[int, str] = {}

    async def scenario() -> None:
        result.update(await coro)

    run(scenario())
    return result


def wired(*found: Run, broken: bool = False) -> CountingRuns:
    fake = CountingRuns(list(found), broken)
    services.register(Runs, fake)
    return fake


L = limits(carried=3, script=50, output=50)
Q, ANS, SAID = turn(1), turn(2, "ashley", answers=1), turn(3)


def test_a_run_comes_under_the_answer_to_the_turn_that_asked_for_it() -> None:
    r = stored(1, 1, "print(1)", out("one"))
    wired(r)
    assert go(carried(1, [Q, ANS], SAID, L)) == {2: block(r, L)}


def test_runs_of_one_question_keep_the_order_they_ran_in() -> None:
    first, second = stored(1, 1, "AAA", out("o")), stored(2, 1, "BBB", out("o"))
    wired(first, second)
    text = go(carried(1, [Q, ANS], SAID, L))[2]
    assert block(first, L) in text and block(second, L) in text
    assert text.index("AAA") < text.index("BBB")


def test_runs_of_different_questions_go_under_their_own_answers() -> None:
    q2, a2 = turn(3), turn(4, "ashley", answers=3)
    r1, r2 = stored(1, 1, "AAA", out("o")), stored(2, 3, "BBB", out("o"))
    wired(r1, r2)
    got = go(carried(1, [Q, ANS, q2, a2], turn(5), L))
    assert set(got) == {2, 4} and "AAA" in got[2] and "BBB" not in got[2] and "BBB" in got[4]


def test_only_the_answer_with_runs_is_in_the_result() -> None:
    q2, a2 = turn(3), turn(4, "ashley", answers=3)
    wired(stored(1, 3, "BBB", out("o")))
    assert set(go(carried(1, [Q, ANS, q2, a2], turn(5), L))) == {4}


def test_one_read_for_the_person_turns_carried_with_the_household_and_budget() -> None:
    q2, a2 = turn(3), turn(4, "ashley", answers=3)
    fake = wired()
    assert go(carried(9, [Q, ANS, q2, a2], turn(5), limits(carried=2))) == {}
    assert fake.reads == [(9, (1, 3), 2)]


def test_no_read_when_no_person_turn_is_carried() -> None:
    fake = wired()
    assert go(carried(1, [ANS], SAID, L)) == {}
    assert go(carried(1, [], SAID, L)) == {}
    assert fake.reads == []


def test_no_read_and_no_runs_when_the_budget_is_zero() -> None:
    fake = wired(stored(1, 1, "AAA", out("o")))
    assert go(carried(1, [Q, ANS], SAID, limits(carried=0))) == {}
    assert fake.reads == []


def test_a_run_whose_answer_is_not_carried_comes_nowhere() -> None:
    wired(stored(1, 1, "AAA", out("o")))
    assert go(carried(1, [Q], SAID, L)) == {}


def test_a_run_of_a_question_still_waiting_on_its_answer_comes_nowhere() -> None:
    wired(stored(1, 1, "AAA", out("o")))
    held = turn(2, "ashley", follows=True, answers=1)
    assert go(carried(1, [Q, held], turn(3), L)) == {}
    wired(stored(1, 1, "AAA", out("o")))
    assert go(carried(1, [Q], Q, L)) == {}


def test_a_held_line_is_never_the_answer_a_run_comes_under() -> None:
    wired(stored(1, 1, "AAA", out("o")))
    held = turn(2, "ashley", follows=True, answers=1)
    assert go(carried(1, [Q, held], SAID, L)) == {}


def test_a_run_of_no_carried_turn_comes_nowhere() -> None:
    wired(stored(1, 99, "AAA", out("o")), stored(2, None, "BBB", out("o")))
    assert go(carried(1, [Q, ANS], SAID, L)) == {}


def test_conversations_are_placed_apart() -> None:
    p1, a1 = turn(1, conversation=1), turn(5, "ashley", conversation=1, answers=1)
    p2, a2 = turn(2, conversation=2), turn(3, "ashley", conversation=2, answers=2)
    r1, r2 = stored(1, 1, "AAA", out("o")), stored(2, 2, "BBB", out("o"))
    wired(r1, r2)
    got = go(carried(1, [p1, p2, a2, a1], turn(6, conversation=2), L))
    assert "AAA" in got[5] and "BBB" not in got[5]
    assert "BBB" in got[3] and "AAA" not in got[3]


def test_unreadable_runs_leave_the_reply_without_them_and_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    wired(broken=True)
    with caplog.at_level(logging.DEBUG):
        assert go(carried(1, [Q, ANS], SAID, L)) == {}
    assert any("respond.runs_unavailable" in r.getMessage() for r in caplog.records)


def test_the_text_never_holds_the_input_of_a_run() -> None:
    wired(stored(1, 1, "s", out("o"), stdin="SECRETSTDIN", files={"f": "SECRETFILE"}))
    assert "SECRET" not in go(carried(1, [Q, ANS], SAID, L))[2]
