"""Undo's window from the contract alone: an Undo naming a command with `seq < next_seq - undo_window` is refused
`nothing_to_undo`, one at `seq == next_seq - undo_window` is decided by the ordinary rules, and refusals, Runs and
accepted Undos each spend a slot of the window like any change."""

import pytest
from ashley.workshop.commands import Command
from ashley.workshop.decide import EMPTY, Refused, decide
from hypothesis import given, settings
from hypothesis import strategies as st
from ll_support import accepted, add, bad, fold, reason, rules, run_cmd, undo


@pytest.mark.parametrize("window", [1, 2, 4])
@pytest.mark.parametrize("extra", [0, 1, 3])
def test_the_oldest_command_inside_the_window_can_be_undone_and_the_one_before_it_cannot(window: int, extra: int) -> None:
    n = window + extra
    adds: list[Command] = [add() for _ in range(n)]
    edge = n + 1 - window
    assert accepted(fold([*adds, undo(edge)], window)[-1])
    if edge > 1:
        assert reason(fold([*adds, undo(edge - 1)], window)[-1]) == "nothing_to_undo"
        assert accepted(fold([*adds, undo(edge - 1)], 1000)[-1]), "control: the refusal is the window's"


def test_an_undo_older_than_the_window_is_refused_whatever_the_command_it_names() -> None:
    commands: list[Command] = [add(), add("code"), add()]
    assert reason(fold([*commands, bad(), bad(), undo(1)], 3)[-1]) == "nothing_to_undo"
    assert reason(fold([*commands, bad(), bad(), undo(2)], 3)[-1]) == "nothing_to_undo"
    assert accepted(fold([*commands, bad(), undo(2)], 3)[-1])


@pytest.mark.parametrize("window", [2, 3, 4])
@pytest.mark.parametrize("filler", [0, 1, 2, 3])
def test_refusals_spend_slots_of_the_window(window: int, filler: int) -> None:
    got = fold([add(), *[bad() for _ in range(filler)], undo(1)], window)
    assert all(isinstance(d, Refused) for d in got[1:-1])
    next_seq = 2 + filler
    assert (not isinstance(got[-1], Refused)) == (1 >= next_seq - window)
    if isinstance(got[-1], Refused):
        assert got[-1].reason == "nothing_to_undo"


@pytest.mark.parametrize("window", [3, 4])
@pytest.mark.parametrize("runs", [0, 1, 2, 3])
def test_runs_spend_slots_of_the_window(window: int, runs: int) -> None:
    got = fold([add("code"), add(), *[run_cmd(1) for _ in range(runs)], undo(2)], window)
    assert all(not isinstance(d, Refused) for d in got[:-1])
    next_seq = 3 + runs
    if 2 >= next_seq - window:
        accepted(got[-1])
    else:
        assert reason(got[-1]) == "nothing_to_undo"


@pytest.mark.parametrize("window", [2, 3])
def test_accepted_undos_spend_slots_of_the_window(window: int) -> None:
    got = fold([add(), add(), undo(2), undo(1)], window)
    assert all(not isinstance(d, Refused) for d in got[:3])
    if 1 >= 4 - window:
        accepted(got[-1])
    else:
        assert reason(got[-1]) == "nothing_to_undo"


@settings(max_examples=40, deadline=None)
@given(window=st.integers(1, 5), ops=st.lists(st.one_of(st.just("add"), st.just("bad"), st.integers(0, 14)), max_size=14))
def test_no_undo_outside_the_window_is_ever_taken(window: int, ops: list[str | int]) -> None:
    state = EMPTY
    for op in ops:
        command = add() if op == "add" else bad() if op == "bad" else undo(int(op))
        before = state.next_seq
        decision = decide(state, command, rules(window))
        if not isinstance(op, str) and op < before - window:
            assert isinstance(decision, Refused) and decision.reason == "nothing_to_undo"
        state = decision.state
