"""Directed tests for what the planted-mutant run found no test could tell apart."""

import pytest
from agree_tap_blind_support import LOG_ID, LOG_REASON, world, log_lines
from ashley import services
from ashley.live.events import ThreadTurn
from ashley.live.live import Live
from later_support import Logged
from live_support import FakeLive


def test_a_proposal_that_lapses_before_a_resumed_turn_takes_it_is_logged_refused_as_expired(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.die_after_begin = True
        w.tap_dying(w.alana, pid)
        w.age(pid)
        w.settle()
        text = log.read()
    refused = [f for f in log_lines(text) if f.get("event") == "agree.refused" and f.get(LOG_ID) == str(pid)]
    assert [f.get(LOG_REASON) for f in refused] == ["expired"]
    assert w.tools.ran == [] and w.work_rows() == 0


def test_a_tap_tells_the_screens_twice_once_for_the_person_turn_and_once_for_her_answer(db_url: str) -> None:
    live = FakeLive()
    with world(db_url) as w:
        services.register(Live, live)
        try:
            pid = w.hold(w.alana)
            w.tap(w.alana, pid)
        finally:
            services.unregister(Live)
    assert sum(isinstance(e, ThreadTurn) for e in live.published) == 2
