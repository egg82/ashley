"""Logs name the proposal and the reason a tap was refused; never what the held calls were or said."""

import pytest
from agree_tap_blind_support import LOG_ID, LOG_REASON, REASONS, ROOM, SUMMARY, world, log_lines
from later_support import Logged


def line_naming(text: str, pid: int) -> list[dict[str, str]]:
    return [f for f in log_lines(text) if f.get(LOG_ID) == str(pid)]


def test_a_taken_tap_logs_the_proposal_id_and_none_of_its_content(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.tap(w.alana, pid)
        w.settle()
        text = log.read()
    assert line_naming(text, pid), "no agree event names the proposal"
    assert ROOM not in text and SUMMARY not in text


@pytest.mark.parametrize("case", ["other_person", "other_household", "expired", "unknown"])
def test_a_refusal_logs_the_reason_beside_the_proposal_and_none_of_its_content(
        db_url: str, capsys: pytest.CaptureFixture[str], case: str) -> None:
    log = Logged(capsys)
    with world(db_url) as w:
        pid = w.hold(w.alana)
        if case == "expired":
            w.age(pid)
        who = {"other_person": w.sam, "other_household": w.zed}.get(case, w.alana)
        asked = 987_654 if case == "unknown" else pid
        w.tap(who, asked)
        w.settle()
        text = log.read()
    named = line_naming(text, asked)
    assert any(f.get(LOG_REASON) == REASONS[case] for f in named), f"{case}: no line names proposal and reason"
    assert ROOM not in text and SUMMARY not in text


def test_a_resumed_carry_out_logs_no_content(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.die_after_begin = True
        w.tap_dying(w.alana, pid)
        w.settle()
        text = log.read()
    assert len(w.tools.ran) == 2 and ROOM not in text and SUMMARY not in text
