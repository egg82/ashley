from dataclasses import replace
from datetime import datetime, timezone
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

from ashley.conversations.model import Kind
from ashley.people.model import Household, Person
from ashley.persona import facts
from ashley.persona.persona import Context, system

ALANA = Person(1, 1, "Alana")
SAM = Person(2, 1, "Sam")
HOME = Household(1, "home", "America/Denver", "A profile line.", (ALANA, SAM))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
CONTEXT = Context(NOW, HOME, ALANA, frozenset({1, 2}), "kitchen", "Tool guidance.", True)


def test_stable_sections_come_first_and_the_moment_last():
    for kind in get_args(Kind):
        prompt = system(kind, CONTEXT)["default"].text
        order = ["# Ashley", "# This conversation", "# Tools\n\nTool guidance.", "# This household", "# Now"]
        at = [prompt.index(heading) for heading in order]
        assert at == sorted(at)


def household_in(locale: str) -> Household:
    return replace(HOME, locale=locale)


def test_an_english_household_gets_no_language_line() -> None:
    for locale in ("en-US", "en-GB", "en"):
        for kind in get_args(Kind):
            assert facts.LANGUAGE.split("{name}")[0] not in system(
                kind, replace(CONTEXT, household=household_in(locale)))["default"].text


def test_a_german_household_prompt_names_german_and_differs_only_by_that_line() -> None:
    line = facts.LANGUAGE.format(name="German")
    for kind in get_args(Kind):
        english = system(kind, CONTEXT)["default"]
        german = system(kind, replace(CONTEXT, household=household_in("de-DE")))["default"]
        assert german.stable.count(line) == 1
        assert german.stable.replace("\n\n" + line, "") == english.stable and german.moment == english.moment


def test_a_locale_with_no_known_language_adds_no_line() -> None:
    assert system("chat", replace(CONTEXT, household=household_in("xx-YY")))["default"] == system("chat", CONTEXT)["default"]


def test_with_no_variants_shipped_there_is_only_the_default():
    assert list(system("command", CONTEXT)) == ["default"]


def test_the_facts_name_the_moment_the_speaker_who_is_home_and_the_place():
    prompt = system("chat", CONTEXT)["default"].text
    for line in [
        "It is Sunday 25 October 2026, 7:34 pm.",
        "A profile line.",
        "Alana is speaking.",
        "Home now: Alana and Sam.",
        "kitchen",
    ]:
        assert line in prompt


def test_unknowns_and_an_unreachable_house_are_said_so():
    prompt = system("chat", replace(CONTEXT, speaker=None, home=None, place=None, tools_reachable=False))["default"].text
    assert "You don't know who is speaking." in prompt
    assert "You don't know who is home." in prompt
    assert facts.UNREACHABLE in prompt and prompt.index(facts.UNREACHABLE) < prompt.index("# Now")
    assert "Tool guidance." not in prompt


def test_nobody_home_is_not_unknown():
    assert "Nobody is home." in system("command", replace(CONTEXT, home=frozenset()))["default"].text


def test_an_empty_profile_adds_only_the_units():
    prompt = system("command", replace(CONTEXT, household=replace(HOME, profile="  ")))["default"].text
    assert "# This household\n\n" + facts.UNITS["imperial"] + "\n\n" in prompt and "A profile line." not in prompt


@pytest.mark.parametrize(
    ("hour", "minute", "said"), [(0, 5, "12:05 am"), (12, 0, "12:00 pm"), (11, 59, "11:59 am"), (23, 1, "11:01 pm")]
)
def test_times_are_twelve_hour(hour: int, minute: int, said: str):
    assert facts.when(datetime(2026, 10, 25, hour, minute, tzinfo=timezone.utc)).endswith(said)


@pytest.mark.parametrize(
    "bad",
    [
        replace(CONTEXT, now=datetime(2026, 10, 25, 19, 34)),
        replace(CONTEXT, speaker=Person(3, 1, "Stranger")),
        replace(CONTEXT, home=frozenset({1, 9})),
    ],
)
def test_contexts_that_cannot_be_true_are_refused(bad: Context):
    with pytest.raises(ValueError):
        system("command", bad)


def test_the_same_arguments_give_the_same_text():
    assert system("brainstorm", CONTEXT) == system("brainstorm", CONTEXT)


def test_a_source_that_did_not_answer_is_said_after_the_guidance():
    prompt = system("chat", replace(CONTEXT, tools_unreachable=("house", "search", "other")))["default"].text
    section = prompt[prompt.index("# Tools"):prompt.index("# This household")]
    assert section.strip() == ("# Tools\n\nTool guidance.\n\n" + facts.UNREACHABLE
                               + " You can't look things up right now. Say so if asked.")


def test_tools_with_nothing_to_say_add_no_section():
    assert facts.tools(None, True, ()) is None
    assert facts.tools("  ", True, ("other",)) is None
    assert facts.tools(None, True, ("search",)) == "# Tools\n\nYou can't look things up right now. Say so if asked."
    assert facts.tools(None, True, ("web", "places")) is None
    assert facts.tools("G.", False, ("search",)) == "# Tools\n\n" + facts.UNREACHABLE


def test_said_before_sits_between_what_she_remembers_and_the_moment():
    prompt = system("chat", replace(CONTEXT, said_before=("(2 days ago) Alana: the gate squeaks",)))["default"].text
    assert prompt.index("# Tools") < prompt.index("# Said before") < prompt.index("# Now")
    assert "(2 days ago) Alana: the gate squeaks" in prompt
    assert "# Said before" not in system("chat", CONTEXT)["default"].text


def test_what_was_done_while_they_were_away_sits_between_what_was_said_and_the_moment():
    prompt = system("chat", replace(CONTEXT, said_before=("(x) Alana: hi",), while_away=("(Friday 9 am) added milk",)))["default"].text
    assert prompt.index("# Said before") < prompt.index("# While they were away") < prompt.index("# Now")
    assert "(Friday 9 am) added milk" in prompt
    assert "# While they were away" not in system("chat", CONTEXT)["default"].text
