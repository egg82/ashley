"""`ashley.memory.report.seen`: which `respond.done` and `memory.apply` lines belong to a conversation, in order, once.
Lines are made by the app's own formatter. Written blind from the contract."""

import random
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest
from ashley.memory.report import ReplySeen, WriteSeen, seen

from report_support import T0, applied, at, done, line, stamp


def replies(lines: list[str], conversation: int = 7) -> tuple[ReplySeen, ...]:
    return seen(lines, conversation)[0]


def writes(lines: list[str], conversation: int = 7) -> tuple[WriteSeen, ...]:
    return seen(lines, conversation)[1]


def test_only_the_conversations_own_lines_are_kept() -> None:
    lines = [done(7, at(1), kind="chat"), done(8, at(2), kind="command"), done(77, at(3), kind="brainstorm"),
             done(17, at(4)), applied(7, at(5), add=1), applied(8, at(6), add=2), applied(70, at(7))]
    got_replies, got_writes = seen(lines, 7)
    assert [r.kind for r in got_replies] == ["chat"]
    assert [w.add for w in got_writes] == [1]


def test_other_events_for_the_conversation_are_ignored() -> None:
    lines = [line("respond.failed", conversation=7, reason="x"), line("memory.profile", household=1, count=2),
             line("memory.apply_refused", household=1, conversation=7, reason="constraint"),
             line("memory.write_unembedded", household=1, facts="1,2"), "not a log line", "", done(7, at(1))]
    got_replies, got_writes = seen(lines, 7)
    assert len(got_replies) == 1 and got_writes == ()


def test_nothing_in_nothing_out() -> None:
    assert seen([], 7) == ((), ())
    assert seen(["junk", "", "ts=1"], 7) == ((), ())


def test_a_reply_carries_its_fields() -> None:
    (r,) = replies([done(7, at(1.25), standing="30,4", recalled="9,2,5", used="2,30", unrecalled=3, kind="command",
                        medium="spoken", speaker="unknown")])
    assert r.at == stamp(at(1.25))
    assert (r.kind, r.medium, r.speaker) == ("command", "spoken", "unknown")
    assert r.standing == (30, 4) and r.recalled == (9, 2, 5)
    assert r.used == (2, 30) and r.used_unrecalled == 3
    assert r.known_offered is True


def test_the_offered_order_is_kept_not_sorted() -> None:
    (r,) = replies([done(7, standing="30,4,18", recalled="900,5", used="900,18,4")])
    assert r.standing == (30, 4, 18) and r.recalled == (900, 5) and r.used == (900, 18, 4)


def test_empty_tiers_are_empty_tuples_and_offered() -> None:
    (r,) = replies([done(7, standing="", recalled="", used="")])
    assert r.standing == () and r.recalled == () and r.used == ()
    assert r.known_offered is True


def test_an_unavailable_tier_is_none() -> None:
    (both,) = replies([done(7, standing="unavailable", recalled="unavailable")])
    assert both.standing is None and both.recalled is None
    (one,) = replies([done(7, standing="8,9", recalled="unavailable")])
    assert one.standing == (8, 9) and one.recalled is None


def test_an_old_line_without_the_tier_fields_is_unknown_not_empty() -> None:
    (r,) = replies([done(7, standing=None, recalled=None, used="3,4", unrecalled=1)])
    assert r.standing is None and r.recalled is None
    assert r.known_offered is False
    assert r.used == (3, 4) and r.used_unrecalled == 1


def test_a_current_line_and_an_old_line_differ_in_known_offered() -> None:
    old, new = replies([done(7, at(1), standing=None, recalled=None), done(7, at(2), standing="", recalled="")])
    assert (old.known_offered, new.known_offered) == (False, True)


@pytest.mark.parametrize("field, value", [("standing", "1,x"), ("recalled", "abc"), ("used", "1,two"),
                                          ("standing", "1;2"), ("recalled", "1, 2 x")])
def test_a_malformed_id_list_drops_that_line_only(field: str, value: str) -> None:
    bad = done(7, at(1), standing=value if field == "standing" else "1", recalled=value if field == "recalled" else "2",
               used=value if field == "used" else "2")
    good = done(7, at(2), kind="command", standing="1", recalled="2", used="2")
    got = replies([bad, good])
    assert [r.kind for r in got] == ["command"]


def test_a_malformed_inserted_list_drops_that_write_only() -> None:
    got = writes([applied(7, at(1), inserted="4,z", add=2), applied(7, at(2), inserted="5,6", add=2)])
    assert [w.inserted for w in got] == [(5, 6)]


def test_a_write_carries_its_fields() -> None:
    (w,) = writes([applied(7, at(3), inserted="21,22", add=2, update=1, invalidate=3, forget=4, noop=5, deleted=6,
                           written_through=99)])
    assert w.at == stamp(at(3)) and w.inserted == (21, 22)
    assert (w.add, w.update, w.invalidate, w.forget, w.noop, w.deleted) == (2, 1, 3, 4, 5, 6)
    assert w.written_through == 99


def test_a_write_with_nothing_inserted_or_written_through() -> None:
    (w,) = writes([applied(7, at(3), inserted="", noop=1)])
    assert w.inserted == () and w.written_through is None and w.noop == 1


def test_replies_are_ordered_by_time_whatever_the_input_order() -> None:
    kinds = ["a", "b", "c", "d", "e", "f"]
    lines = [done(7, at(i * 0.5 - 1), kind=k) for i, k in enumerate(kinds)]
    for order in (list(reversed(lines)), random.Random(1).sample(lines, 6), random.Random(2).sample(lines, 6)):
        assert [r.kind for r in replies(order)] == kinds


def test_writes_are_ordered_by_time_whatever_the_input_order() -> None:
    lines = [applied(7, T0 + timedelta(hours=i), add=i) for i in range(6)]
    for order in (list(reversed(lines)), random.Random(3).sample(lines, 6)):
        assert [w.add for w in writes(order)] == list(range(6))


def test_two_sites_interleave_into_one_order() -> None:
    site_a = [done(7, at(1), kind="a"), done(7, at(5), kind="c")]
    site_b = [done(7, at(3), kind="b"), done(7, at(7), kind="d")]
    assert [r.kind for r in replies(site_a + site_b)] == ["a", "b", "c", "d"]


def test_the_same_line_twice_counts_once() -> None:
    one = done(7, at(1), kind="a")
    assert len(replies([one, one, one])) == 1
    w = applied(7, at(2), add=1)
    assert len(writes([w, w])) == 1


def test_different_lines_at_the_same_instant_both_count() -> None:
    same = at(1)
    got = replies([done(7, same, kind="a"), done(7, same, kind="b")])
    assert sorted(r.kind for r in got) == ["a", "b"]
    assert len(writes([applied(7, same, add=1), applied(7, same, add=2)])) == 2


def test_the_results_are_tuples_and_frozen() -> None:
    got_replies, got_writes = seen([done(7), applied(7, add=1)], 7)
    assert isinstance(got_replies, tuple) and isinstance(got_writes, tuple)
    assert isinstance(got_replies[0].used, tuple) and isinstance(got_writes[0].inserted, tuple)
    with pytest.raises(FrozenInstanceError):
        setattr(got_replies[0], "kind", "x")
    with pytest.raises(FrozenInstanceError):
        setattr(got_writes[0], "add", 9)


def test_lines_may_be_any_iterable_and_carry_newlines() -> None:
    gen = (ln + "\n" for ln in [done(7, at(1)), done(7, at(2), kind="command")])
    assert [r.kind for r in seen(gen, 7)[0]] == ["chat", "command"]
