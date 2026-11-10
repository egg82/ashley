"""`persona.system`, structure only, never the wording: one prompt per variant under `variants/` plus `default`; each
is the persona, the kind's rules, the tool instructions (or the unreachable line), the household profile when
non-empty, then the facts of the moment last (date and time with weekday, the speaker, who is home, the place);
ValueErrors for what cannot be true; deterministic. Section positions are found by the first non-empty line of each
prose file and by planted values."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from ashley.conversations.model import Kind
from ashley.people.model import Household, Person
from ashley.persona import persona as persona_module
from ashley.persona.persona import Context, system
from ashley.persona.sections import MARKER_PREFIX
from conversations_support import KINDS

HERE = Path(persona_module.__file__).parent
AVERY, BLAIR, CASEY = Person(1, 9, "zqAvery"), Person(2, 9, "zqBlair"), Person(3, 9, "zqCasey")
HOUSEHOLD = Household(9, "home", "America/Denver", "zqPROFILE a dog named Pip", (AVERY, BLAIR, CASEY))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))   # a Sunday
CONTEXT = Context(NOW, HOUSEHOLD, AVERY, frozenset({AVERY.id, BLAIR.id}), "zqPLACE", "zqTOOLS use them well", True)
ANY_KIND: Any = "not-a-kind"


def first_line(path: Path) -> str:
    """The first line of the file that reaches a prompt: a section marker line (`persona.sections`) never does."""
    return next(line.strip() for line in path.read_text().splitlines()
                if line.strip() and not line.startswith(MARKER_PREFIX))


def variants() -> set[str]:
    folder = HERE / "variants"
    return {p.name for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()


def source(kind: Kind, variant: str, name: str) -> Path:
    """The file a variant's prompt is built from: its override when it has one, else the shared one."""
    override = HERE / "variants" / variant / name
    return override if override.is_file() else HERE / name


@pytest.mark.parametrize("kind", KINDS)
def test_one_prompt_per_variant_plus_default(kind: Kind) -> None:
    got = system(kind, CONTEXT)
    assert set(got) == {"default"} | variants()
    assert all(v.text.strip() for v in got.values())


@pytest.mark.parametrize("kind", KINDS)
def test_sections_come_in_order_with_the_facts_last(kind: Kind) -> None:
    for variant, prompt in system(kind, CONTEXT).items():
        text = prompt.text
        persona = text.index(first_line(source(kind, variant, "ashley.md")))
        rules = text.index(first_line(source(kind, variant, f"kinds/{kind}.md")))
        tools = text.index("zqTOOLS")
        profile = text.index("zqPROFILE")
        facts = [text.index(fact) for fact in ("Sunday", "zqAvery", "zqBlair", "zqPLACE")]
        assert persona < rules < tools < profile < min(facts), variant


def test_each_kind_has_its_own_rules() -> None:
    texts = {kind: system(kind, CONTEXT)["default"].text for kind in KINDS}
    for kind in KINDS:
        assert first_line(HERE / "kinds" / f"{kind}.md") in texts[kind]
    assert len(set(texts.values())) == len(KINDS)


def test_the_facts_are_rendered() -> None:
    text = system("chat", CONTEXT)["default"].text
    for fact in ("Sunday", "2026", "zqAvery", "zqBlair", "zqPLACE", "zqPROFILE", "zqTOOLS"):
        assert fact in text
    assert "zqCasey" not in text, "someone neither speaking nor home is not named"


def test_the_time_of_day_and_the_date_are_facts() -> None:
    base = system("chat", CONTEXT)["default"].text
    later = system("chat", replace(CONTEXT, now=NOW + timedelta(hours=3, minutes=7)))["default"].text
    tomorrow = system("chat", replace(CONTEXT, now=NOW + timedelta(days=1)))["default"].text
    assert len({base, later, tomorrow}) == 3
    assert "Monday" in tomorrow and "Sunday" not in tomorrow


@pytest.mark.parametrize(("changed", "absent"), [
    ({"speaker": None}, None),
    ({"home": None}, "zqBlair"),
    ({"home": frozenset[int]()}, "zqBlair"),
    ({"place": None}, "zqPLACE"),
    ({"household": replace(HOUSEHOLD, profile="")}, "zqPROFILE"),
])
def test_each_fact_changes_the_prompt_and_an_unknown_one_names_nothing(changed: dict[str, Any],
                                                                       absent: str | None) -> None:
    text = system("chat", replace(CONTEXT, **changed))["default"].text
    assert text != system("chat", CONTEXT)["default"].text
    if absent:
        assert absent not in text


def test_unknown_home_and_nobody_home_read_differently() -> None:
    unknown = system("chat", replace(CONTEXT, home=None))["default"].text
    nobody = system("chat", replace(CONTEXT, home=frozenset()))["default"].text
    assert unknown != nobody


def test_unreachable_tools_say_so_instead_of_instructions() -> None:
    reachable = system("command", replace(CONTEXT, tool_instructions=None))["default"].text
    unreachable = system("command", replace(CONTEXT, tool_instructions=None, tools_reachable=False))["default"].text
    assert reachable != unreachable
    assert len(unreachable) > len(reachable), "one line is added"
    text = system("command", replace(CONTEXT, tools_reachable=False))["default"].text
    assert "zqTOOLS" not in text


def test_deterministic() -> None:
    for kind in KINDS:
        assert system(kind, CONTEXT) == system(kind, CONTEXT)


def test_a_stable_prefix_survives_the_clock_moving() -> None:
    """Everything before the facts is the same at two moments, so a cached prefix stays cached."""
    one = system("chat", CONTEXT)["default"].text
    two = system("chat", replace(CONTEXT, now=NOW + timedelta(minutes=1)))["default"].text
    cut = one.index("zqPROFILE") + len("zqPROFILE")
    assert one[:cut] == two[:cut]


@pytest.mark.parametrize("bad", [
    {"now": NOW.replace(tzinfo=None)},
    {"speaker": Person(77, 9, "zqStranger")},
    {"home": frozenset({AVERY.id, 77})},
])
def test_what_cannot_be_true_is_a_value_error(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        system("chat", replace(CONTEXT, **bad))


def test_a_kind_with_no_file_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        system(ANY_KIND, CONTEXT)

