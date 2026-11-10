"""The shipped `watches.json` loads, and its claude_session kind is the spec's."""

from ashley.criteria import condition
from ashley.watches.config import CONFIG, load


def test_the_claude_session_kind_has_the_spec_values() -> None:
    kind = load().kinds["claude_session"]
    assert (kind.interval_s, kind.hours, kind.max_hours, kind.handoff_hours) == (15, 24, 168, 72)
    assert kind.track == ("status", "seq")
    assert len(kind.when) == 2 and len(kind.when[0]) == 2 and len(kind.when[1]) == 3
    assert condition.to_json(kind.handoff_until) == [[{"kind": "gone", "negate": False}]]


def test_the_default_when_wakes_for_a_stop_and_not_for_a_look_at_the_finish() -> None:
    from ashley.criteria.record import Change
    when = CONFIG.kinds["claude_session"].when
    stop = Change("s", "changed", {"status": "working", "seq": 1}, {"status": "done", "seq": 2})
    seen = Change("s", "changed", {"status": "done", "seq": 2}, {"status": "idle", "seq": 2})
    working = Change("s", "changed", {"status": "idle", "seq": 2}, {"status": "working", "seq": 3})
    assert condition.satisfied(when, [stop])
    assert not condition.satisfied(when, [seen]) and not condition.satisfied(when, [working])
