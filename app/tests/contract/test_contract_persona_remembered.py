"""`persona.system` and `facts.remembered` for what memory recalled: a `# What you remember` section after the household
profile and before the `# Now` facts, one `[id] text` line per fact in the order given, `(only if asked) ` for a fact she
may not volunteer, one unreachable line when memory could not be reached, no section when nothing was recalled."""

from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from ashley.conversations.model import Kind
from ashley.memory.model import Fact, Recalled
from ashley.people.model import Household, Person
from ashley.persona import facts
from ashley.persona.persona import Context, system
from conversations_support import KINDS

AVERY = Person(1, 9, "zqAvery")
HOUSEHOLD = Household(9, "home", "America/Denver", "zqPROFILE a dog named Pip", (AVERY,))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
HEADER = "# What you remember"
FACT_A, FACT_B, FACT_C = "zqFactA tea at six", "zqFactB the spare key is under the mat", "zqFactC [7] a bracketed one"


def fact(fact_id: int, text: str) -> Fact:
    return Fact(fact_id, 9, None, None, "shared", "other", False, text, 1, NOW, None, None)


A = Recalled(fact(907, FACT_A), True)
B = Recalled(fact(31, FACT_B), False)
C = Recalled(fact(5, FACT_C), True)
BASE = Context(NOW, HOUSEHOLD, AVERY, frozenset({AVERY.id}), "zqPLACE", "zqTOOLS use them well", True)


def prompt(kind: Kind = "chat", **changed: Any) -> str:
    return system(kind, replace(BASE, **changed))["default"].text


def lines(text: str) -> list[str]:
    return text.splitlines()


def test_remembered_defaults_to_empty() -> None:
    assert BASE.remembered == ()


def test_each_fact_is_one_id_and_text_line_in_the_order_given() -> None:
    text = prompt(remembered=(A, B, C))
    ls = lines(text)
    assert "[907] (learned Sun 25 Oct 2026 19:34) zqFactA tea at six" in ls
    assert "[31] (learned Sun 25 Oct 2026 19:34) (only if asked) zqFactB the spare key is under the mat" in ls
    assert "[5] (learned Sun 25 Oct 2026 19:34) zqFactC [7] a bracketed one" in ls
    assert ls.index("[907] (learned Sun 25 Oct 2026 19:34) zqFactA tea at six") < ls.index("[31] (learned Sun 25 Oct 2026 19:34) (only if asked) zqFactB the spare key is under the mat") \
        < ls.index("[5] (learned Sun 25 Oct 2026 19:34) zqFactC [7] a bracketed one")


def test_the_given_order_is_kept_not_sorted_by_id_or_text() -> None:
    ls = lines(prompt(remembered=(C, B, A)))
    found = [i for i, line in enumerate(ls) if line.startswith(("[907]", "[31]", "[5]"))]
    assert [ls[i][:3] for i in found] == ["[5]", "[31", "[90"]
    assert found == sorted(found)


def test_only_a_fact_she_may_not_volunteer_carries_the_marker() -> None:
    ls = lines(prompt(remembered=(A, B)))
    fact_lines = [line for line in ls if line.startswith("[")]
    assert len(fact_lines) == 2
    (marked,) = [line for line in fact_lines if "(only if asked)" in line]
    assert marked.startswith("[31] ") and FACT_B in marked
    free = next(line for line in ls if FACT_A in line)
    assert free == "[907] (learned Sun 25 Oct 2026 19:34) " + FACT_A


@pytest.mark.parametrize("volunteer", [True, False])
def test_the_marker_sits_between_the_id_and_the_text(volunteer: bool) -> None:
    got = facts.remembered((Recalled(fact(12, "zqOne"), volunteer),), NOW)
    assert got is not None
    line = next(ln for ln in lines(got) if ln.startswith("[12]"))
    assert line == ("[12] (learned Sun 25 Oct 2026 19:34) zqOne" if volunteer else "[12] (learned Sun 25 Oct 2026 19:34) (only if asked) zqOne")


@pytest.mark.parametrize("kind", KINDS)
def test_the_section_follows_the_profile_and_precedes_the_facts_of_the_moment(kind: Kind) -> None:
    for variant, prompt in system(kind, replace(BASE, remembered=(A, B))).items():
        text = prompt.text
        assert "# Now" in text, variant
        assert text.index("zqPROFILE") < text.index(HEADER) < text.index("[907]") < text.index("# Now"), variant
        assert text.index("# Now") < text.index("Sunday"), variant
        assert text.index("[31]") < text.index("# Now"), variant
        assert text.index("zqTOOLS") < text.index(HEADER), variant


def test_the_section_keeps_its_place_without_a_profile_or_tools() -> None:
    text = prompt(household=replace(HOUSEHOLD, profile=""), tools_reachable=False, tool_instructions=None,
                  remembered=(A,))
    assert text.index(HEADER) < text.index("[907]") < text.index("# Now")
    assert text.count(HEADER) == 1


def test_the_header_is_one_line_of_its_own() -> None:
    assert lines(prompt(remembered=(A,))).count(HEADER) == 1


def test_nothing_recalled_has_no_section_at_all() -> None:
    text = prompt(remembered=())
    assert HEADER not in text
    assert facts.MEMORY_UNREACHABLE not in text
    assert text == prompt()


def test_unreachable_memory_is_one_line_saying_so_under_the_header() -> None:
    text = prompt(remembered=None)
    ls = lines(text)
    assert ls.count(HEADER) == 1
    assert ls.count(facts.MEMORY_UNREACHABLE) == 1
    assert text.index(HEADER) < text.index(facts.MEMORY_UNREACHABLE) < text.index("# Now")
    assert text.index("zqPROFILE") < text.index(HEADER)
    assert not any(line.startswith("[") for line in ls)


def test_none_empty_and_recalled_all_read_differently() -> None:
    assert len({prompt(remembered=None), prompt(remembered=()), prompt(remembered=(A,))}) == 3


def test_recalled_facts_never_show_the_unreachable_line() -> None:
    assert facts.MEMORY_UNREACHABLE not in prompt(remembered=(A, B))


def test_each_fact_changes_the_prompt_and_the_prompt_is_deterministic() -> None:
    assert prompt(remembered=(A,)) != prompt(remembered=(A, B))
    assert prompt(remembered=(A, B)) != prompt(remembered=(B, A))
    assert prompt(remembered=(A, B)) == prompt(remembered=(A, B))
    for kind in KINDS:
        assert system(kind, replace(BASE, remembered=(A, B))) == system(kind, replace(BASE, remembered=(A, B)))


def test_the_prefix_before_the_section_does_not_depend_on_what_was_recalled_or_the_clock() -> None:
    one = prompt(remembered=(A,))
    two = prompt(remembered=(B, C), now=NOW.replace(minute=35))
    cut = one.index("zqPROFILE") + len("zqPROFILE")
    assert one[:cut] == two[:cut]


def test_facts_remembered_matches_the_prompt_section() -> None:
    section = facts.remembered((A, B), NOW)
    assert section is not None and section.startswith(HEADER)
    assert section in prompt(remembered=(A, B))
    assert facts.remembered((), NOW) is None
    unreachable = facts.remembered(None, NOW)
    assert unreachable is not None and unreachable.startswith(HEADER) and facts.MEMORY_UNREACHABLE in unreachable
    assert unreachable in prompt(remembered=None)
