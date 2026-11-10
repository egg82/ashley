"""`proposal_gate.gate` on its own: the turn is judged before the age, and a proposal exactly at its limit is still good."""

from datetime import UTC, datetime, timedelta

from ashley.senses.proposal_gate import gate

AT = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
TTL = 600.0


def test_a_later_turn_exactly_at_the_limit_is_allowed_and_a_moment_past_it_is_expired() -> None:
    assert gate(10, AT, 11, AT + timedelta(seconds=TTL), TTL) is None
    assert gate(10, AT, 11, AT + timedelta(seconds=TTL, microseconds=1), TTL) == "expired"


def test_a_turn_that_is_not_later_is_the_same_turn_even_when_the_proposal_has_expired() -> None:
    late = AT + timedelta(seconds=TTL * 10)
    assert gate(10, AT, 10, late, TTL) == "same_turn"
    assert gate(10, AT, 9, late, TTL) == "same_turn"
    assert gate(10, AT, 11, late, TTL) == "expired"
