"""The report's parsing, joined and rendered on hand-written lines (the contract tests are written apart)."""

from datetime import UTC, datetime

from ashley.memory.model import Fact
from ashley.memory.report import render, seen

DONE = ('ts=2026-10-26T09:00:01.000Z level=info logger=ashley.channels event=respond.done conversation=1 kind=chat '
        'medium=text tool_rounds=0 tool_calls=0 speaker=known recalled=1 standing=1 standing_facts=5 '
        'recalled_facts=7 used_facts=7,9 used_unrecalled=1 duration_ms=40')
OLD = DONE.replace("standing_facts=5 recalled_facts=7 ", "").replace("ts=2026-10-26T09:00:01", "ts=2026-10-26T08:00:01")
APPLY = ('ts=2026-10-26T09:10:00.000Z level=info logger=ashley.memory event=memory.apply household=1 conversation=1 '
         'add=1 update=0 invalidate=0 forget=0 noop=0 deleted=0 inserted=11 written_through=4')


def fact(i: int, text: str, valid_to: datetime | None = None, by: int | None = None) -> Fact:
    return Fact(i, 1, None, None, "shared", "diet", True, text, 3, datetime(2026, 1, 1, tzinfo=UTC), valid_to, by)


def test_lines_are_joined_to_facts_and_ordered() -> None:
    replies, writes = seen([DONE, OLD, DONE, "noise", APPLY, DONE.replace("conversation=1", "conversation=2")], 1)
    assert [r.at[:13] for r in replies] == ["2026-10-26T08", "2026-10-26T09"]
    assert replies[0].standing is None and not replies[0].known_offered
    assert (replies[1].standing, replies[1].recalled, replies[1].used) == ((5,), (7,), (7, 9))
    assert writes[0].inserted == (11,) and writes[0].written_through == 4
    facts = {5: fact(5, "no nuts"), 7: fact(7, "likes tea", datetime(2026, 2, 1, tzinfo=UTC), 12)}
    out = render(1, replies, writes, facts, (("2026-10-26T09:09:00.000Z", "anthropic", "haiku", "ok"),))
    assert "offered facts not logged" in out and "closed 2026-02-01" in out and "replaced by [12]" in out
    assert "[9] forgotten [used, not offered]" in out
    assert '[5] "no nuts"' in out and "[11] forgotten" in out and "anthropic/haiku" in out


def test_unavailable_and_malformed_and_empty() -> None:
    down = DONE.replace("standing_facts=5 recalled_facts=7", "standing_facts=unavailable recalled_facts=unavailable")
    replies, _ = seen([down, DONE.replace("recalled_facts=7", "recalled_facts=x")], 1)
    assert len(replies) == 1 and replies[0].standing is None and replies[0].known_offered
    assert "memory unreachable" in render(1, replies, (), {}, ())
    assert "Nothing found for conversation 9" in render(9, (), (), {}, ())
