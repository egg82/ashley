"""`facts.standing` and the `# What you always know` section of `persona.system`: its content, the `(only if asked)`
marker, absence when empty, its place between the household profile and `# What you remember`, determinism."""

from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from ashley.conversations.model import Kind
from ashley.memory.model import Recalled
from ashley.people.model import Household, Person
from ashley.persona import facts
from ashley.persona.persona import Context, system

from conversations_support import KINDS
from profile_support import stored_fact

AVERY = Person(1, 9, "zqAvery")
HOUSEHOLD = Household(9, "home", "America/Denver", "zqPROFILE a dog named Pip", (AVERY,))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
HEADER = "# What you always know"
REMEMBER = "# What you remember"
BASE = Context(NOW, HOUSEHOLD, AVERY, frozenset({AVERY.id}), "zqPLACE", "zqTOOLS use them well", True)


def standing_fact(fact_id: int, text: str, volunteer: bool = True) -> Recalled:
    return Recalled(stored_fact(fact_id, text, standing=True, household_id=9), volunteer)


def recalled_fact(fact_id: int, text: str) -> Recalled:
    return Recalled(stored_fact(fact_id, text, standing=False, household_id=9), True)


S1 = standing_fact(40, "zqAvery is allergic to shellfish")
S2 = standing_fact(7, "zqAvery uses she and her", volunteer=False)
S3 = standing_fact(65, "zqAvery is vegetarian [3]")
R1 = recalled_fact(907, "zqRecalled tea at six")


def prompt(kind: Kind = "chat", **changed: Any) -> str:
    return system(kind, replace(BASE, **changed))["default"].text


def test_standing_defaults_to_empty() -> None:
    assert BASE.standing == ()


def test_each_standing_fact_is_one_id_and_text_line_in_the_order_given() -> None:
    ls = prompt(standing=(S3, S1, S2)).splitlines()
    wanted = ["[65] (learned Sat 28 Feb 2026 17:00) zqAvery is vegetarian [3]", "[40] (learned Sat 28 Feb 2026 17:00) zqAvery is allergic to shellfish",
              "[7] (learned Sat 28 Feb 2026 17:00) (only if asked) zqAvery uses she and her"]
    assert all(line in ls for line in wanted)
    assert [ls.index(line) for line in wanted] == sorted(ls.index(line) for line in wanted)


def test_only_a_fact_she_may_not_volunteer_carries_the_marker_between_id_and_text() -> None:
    section = facts.standing((S1, S2), NOW)
    assert section is not None
    lines = [ln for ln in section.splitlines() if ln.startswith("[")]
    assert lines == ["[40] (learned Sat 28 Feb 2026 17:00) zqAvery is allergic to shellfish", "[7] (learned Sat 28 Feb 2026 17:00) (only if asked) zqAvery uses she and her"]


def test_the_section_opens_with_its_header_and_an_instruction_naming_used_facts_and_the_marker() -> None:
    section = facts.standing((S1,), NOW)
    assert section is not None and section.startswith(HEADER)
    instruction = section.split("[40]")[0]
    assert "used_facts" in instruction and "(only if asked)" in instruction


def test_the_header_is_one_line_of_its_own_and_appears_once() -> None:
    assert prompt(standing=(S1, S2)).splitlines().count(HEADER) == 1


def test_nothing_standing_has_no_section_at_all() -> None:
    assert facts.standing((), NOW) is None
    text = prompt(standing=())
    assert HEADER not in text
    assert text == prompt()


@pytest.mark.parametrize("kind", KINDS)
def test_the_section_follows_the_profile_and_precedes_what_she_remembers_and_the_facts_of_the_moment(
        kind: Kind) -> None:
    for variant, prompt in system(kind, replace(BASE, standing=(S1, S2), remembered=(R1,))).items():
        text = prompt.text
        assert (text.index("zqPROFILE") < text.index(HEADER) < text.index("[40]") < text.index(REMEMBER)
                < text.index("[907]") < text.index("# Now")), variant
        assert text.index("zqTOOLS") < text.index(HEADER), variant


def test_the_section_keeps_its_place_with_nothing_remembered_and_without_a_profile_or_tools() -> None:
    text = prompt(household=replace(HOUSEHOLD, profile=""), tools_reachable=False, tool_instructions=None,
                  standing=(S1,), remembered=())
    assert text.index(HEADER) < text.index("[40]") < text.index("# Now")
    assert REMEMBER not in text


def test_standing_facts_do_not_appear_under_what_you_remember() -> None:
    text = prompt(standing=(S1,), remembered=(R1,))
    assert text.index("[907]") > text.index(REMEMBER) > text.index("[40]")
    assert text.count("[40]") == 1 and text.count("[907]") == 1


def test_unreachable_memory_is_the_single_line_and_no_standing_section() -> None:
    text = prompt(remembered=None, standing=())
    assert text.splitlines().count(facts.MEMORY_UNREACHABLE) == 1
    assert HEADER not in text


def test_each_standing_fact_changes_the_prompt_and_the_prompt_is_deterministic() -> None:
    assert prompt(standing=(S1,)) != prompt(standing=(S1, S2)) != prompt(standing=(S2, S1))
    assert prompt(standing=(S1, S2)) == prompt(standing=(S1, S2))
    for kind in KINDS:
        assert system(kind, replace(BASE, standing=(S1, S2))) == system(kind, replace(BASE, standing=(S1, S2)))


def test_the_prefix_before_the_section_does_not_depend_on_the_standing_facts_or_the_clock() -> None:
    one = prompt(standing=(S1,))
    two = prompt(standing=(S2, S3), now=NOW.replace(minute=35))
    cut = one.index("zqPROFILE") + len("zqPROFILE")
    assert one[:cut] == two[:cut]


def test_facts_standing_matches_the_prompt_section() -> None:
    section = facts.standing((S1, S2), NOW)
    assert section is not None and section in prompt(standing=(S1, S2))
