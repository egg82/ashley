"""The persona says the household's units in its `# This household` section, for replies and errands alike, profile or
not; and nothing shipped in the persona names a unit system of its own."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from ashley.people.model import Household, Person, UnitSystem
from ashley.persona import errand, facts
from ashley.persona.persona import Context, system

ALANA = Person(1, 1, "Alana")
HOME = Household(1, "home", "Europe/London", "A profile line.", (ALANA,))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("Europe/London"))
CONTEXT = Context(NOW, HOME, ALANA, None, None, None, True)
SPOKEN = {"imperial": "degrees Fahrenheit", "metric": "degrees Celsius"}


def household_section(prompt: str) -> str:
    start = prompt.index("# This household")
    return prompt[start:prompt.index("\n# ", start)]


@pytest.mark.parametrize("units", ["imperial", "metric"])
def test_the_household_section_says_its_units(units: UnitSystem) -> None:
    section = household_section(system("chat", replace(CONTEXT, household=replace(HOME, unit_system=units)))["default"].text)
    assert facts.UNITS[units] in section and SPOKEN[units] in section
    assert "A profile line." in section


def test_a_household_with_no_profile_still_hears_its_units() -> None:
    prompt = system("command", replace(CONTEXT, household=replace(HOME, profile="", unit_system="metric")))["default"].text
    assert household_section(prompt).strip() == "# This household\n\n" + facts.UNITS["metric"]


def test_an_errand_hears_the_units_too() -> None:
    prompt = errand.system(replace(HOME, unit_system="metric"), ALANA, "the house", None, (), NOW)["default"].text
    assert facts.UNITS["metric"] in prompt


def test_the_shipped_persona_names_no_unit_system() -> None:
    shipped = Path(facts.__file__).parent
    for path in shipped.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "Fahrenheit" not in text and "Celsius" not in text, path


THRESHOLD = {"imperial": "more than five degrees", "metric": "more than three degrees"}


@pytest.mark.parametrize("units", ["imperial", "metric"])
def test_the_ask_first_thermostat_threshold_follows_the_units(units: UnitSystem) -> None:
    household = replace(HOME, unit_system=units)
    prompts = [system(kind, replace(CONTEXT, household=household))["default"].text for kind in ("chat", "command")]
    prompts.append(errand.system(household, ALANA, "the house", None, (), NOW)["default"].text)
    for prompt in prompts:
        assert f"a thermostat change of {THRESHOLD[units]}" in prompt
        assert facts.STEP_TOKEN not in prompt
        other = THRESHOLD["metric" if units == "imperial" else "imperial"]
        assert other not in prompt
