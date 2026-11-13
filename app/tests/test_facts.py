"""A facts piece from `decide`'s contract: its body is a JSON object of `items`, each a name (an identifier,
unique in the piece), a finite value, a unit and a source from `facts.UNITS` and `SOURCES`, with an optional
tolerance (above 0 on a `bound` row), ref, checked on every add and edit
(`bad_facts`); her edit of a confirmed row's number alone is refused `confirmed_measurement`."""

import json

import pytest

from ashley.tools import bench_results, bench_specs
from ashley.workshop import facts
from ashley.workshop.commands import Add, Edit
from ashley.workshop.decide import Accepted, Refused, replay
from ashley.workshop.model import By, Text
from ashley.workshop.rules import Kind, Rules, load

KIND = Kind("facts", "stored", "Facts", 2000, "facts")
RULES = Rules({"facts": KIND}, max_pieces=4, title_max_chars=20, recent_commands=10, undo_window=50)
ALANA = By(7)
ITEM = {"name": "board_width", "value": 62.5, "unit": "mm", "source": "measured"}


def body(*items: dict[str, object]) -> str:
    return json.dumps({"items": list(items)})


def item(**changes: object) -> dict[str, object]:
    return {k: v for k, v in {**ITEM, **changes}.items() if v is not None}


def outcome(text: str) -> str:
    seen: set[str] = set()
    for made in (replay([Add(ALANA, "facts", Text("t", text), "medium")], RULES)[-1],
                 replay([Add(ALANA, "facts", Text("t", ""), "medium"), Edit(ALANA, 1, 1, Text("t", text))],
                        RULES)[-1]):
        if isinstance(made, Refused):
            seen.add(made.reason)
        else:
            assert isinstance(made, Accepted)
            seen.add("accepted")
    assert len(seen) == 1
    return seen.pop()


def test_the_shipped_kinds_offer_facts() -> None:
    kind = load().kinds["facts"]
    assert (kind.family, kind.format) == ("stored", "facts")


@pytest.mark.parametrize("text", [
    "", "  ", body(), body(item()),
    body(item(), item(name="hole", value=3, unit="count", source="datasheet", tolerance=0, ref="https://x.example/ds")),
    body(item(unit="deg", source="guessed", tolerance=0.25, ref="")), body(item(value=-4)), body(item(name="_a1")),
    body(item(ref="r" * facts.MAX_REF))])
def test_facts_of_the_shape_are_accepted_on_add_and_edit(text: str) -> None:
    assert outcome(text) == "accepted"


@pytest.mark.parametrize("text", [
    "not json", "[]", "{}", json.dumps({"items": {}}), json.dumps({"items": [], "extra": 1}), json.dumps([ITEM]),
    json.dumps({"items": ["x"]}), body(item(), item()), body(item(), item(value=2)),
    body(item(name=None)), body(item(value=None)), body(item(unit=None)), body(item(source=None)),
    body(item(name="")), body(item(name="9lives")), body(item(name="two words")), body(item(name="a" * 65)),
    body(item(name=3)), body(item(value="62")), body(item(value=True)), body(item(value=None) | {"value": None}),
    body(item(unit="cm")), body(item(unit="MM")), body(item(source="rumour")), body(item(source="")),
    body(item(tolerance=-0.1)), body(item(tolerance="1")), body(item(tolerance=None) | {"tolerance": None}),
    body(item(ref=3)), body(item(ref="r" * (facts.MAX_REF + 1))), body(item(extra=1)),
    '{"items": [{"name": "a", "value": NaN, "unit": "mm", "source": "measured"}]}',
    '{"items": [{"name": "a", "value": Infinity, "unit": "mm", "source": "measured"}]}',
    '{"items": [{"name": "a", "value": 1, "unit": "mm", "source": "measured", "tolerance": NaN}]}',
    '{"items": [{"name": "a", "value": 1' + "0" * 400 + ', "unit": "mm", "source": "measured"}]}'])
def test_facts_outside_the_shape_are_refused_bad_facts(text: str) -> None:
    assert outcome(text) == "bad_facts"


def test_facts_read_back_as_their_fields() -> None:
    got = facts.items_of(body(item(tolerance=0.5, ref="caliper"), item(name="h", value=3, unit="count",
                                                                              source="guessed")))
    assert got == (facts.Measurement("board_width", 62.5, "mm", "measured", 0.5, "caliper"),
                   facts.Measurement("h", 3.0, "count", "guessed", None, None))
    assert facts.items_of("") is None and facts.items_of("{}") is None


@pytest.mark.parametrize("text", [
    body(item(source="accepted")), body(item(source="accepted", tolerance=0, ref="go with it")),
    body(item(source="bound", tolerance=1.5)), body(item(source="bound", tolerance=0.01, unit="count")),
    body(item(unit="g", value=450)), body(item(unit="ml", value=250)), body(item(unit="min", value=90)),
    body(item(source="guessed"))])
def test_accepted_bound_the_plan_units_and_a_guess_are_accepted(text: str) -> None:
    assert outcome(text) == "accepted"


@pytest.mark.parametrize("text", [
    body(item(source="bound")), body(item(source="bound", tolerance=0)), body(item(source="bound", tolerance=-1)),
    body(item(source="guessed", asked=True)), body(item(asked=False)), body(item(source="datasheet", asked=True)),
    body(item(unit="kg")), body(item(unit="l")), body(item(unit="h")), body(item(unit="G")), body(item(source="Accepted"))])
def test_a_bound_without_a_range_and_the_retired_asked_key_are_refused(text: str) -> None:
    assert outcome(text) == "bad_facts"


def test_a_number_is_shown_by_its_value_and_unit_and_a_choice_by_its_value() -> None:
    got = facts.items_of(body(item(value=15, unit="mm"), item(name="b", value=2.5, unit="count")))
    assert got is not None and [facts.shown_value(m) for m in got] == ["15 mm", "2.5 count"]
    assert [facts.shown_label(m) for m in got] == ["board width", "b"]


HER = By(None)
BASE = body(item(source="measured", tolerance=0.5, ref="caliper"), item(name="guess", value=3, source="guessed"),
            item(name="strap", value=20, source="bound", tolerance=1))


def edit_by(by: By, text: str) -> str:
    made = replay([Add(ALANA, "facts", Text("t", BASE), "medium"), Edit(by, 1, 1, Text("t", text))], RULES)[-1]
    return made.reason if isinstance(made, Refused) else "accepted"


def rows(**changes: dict[str, object]) -> str:
    """BASE with the named rows' fields changed; a row changed to {} is dropped."""
    got: list[dict[str, object]] = []
    for row in json.loads(BASE)["items"]:
        change = changes.get(str(row["name"]))
        if change == {}:
            continue
        got.append({k: v for k, v in {**row, **(change or {})}.items() if v is not None})
    return body(*got)


@pytest.mark.parametrize("text", [
    rows(board_width={"value": 61}), rows(board_width={"tolerance": 0.2}), rows(board_width={"unit": "deg"}),
    rows(board_width={"tolerance": None}), rows(strap={"tolerance": 2}), rows(strap={"value": 19}),
    rows(board_width={"value": 61}, guess={"value": 4})])
def test_her_edit_of_a_confirmed_number_alone_is_refused(text: str) -> None:
    assert edit_by(HER, text) == "confirmed_measurement"


@pytest.mark.parametrize("text", [
    BASE, rows(board_width={"value": 61, "ref": "caliper, second reading"}),
    rows(board_width={"value": 61, "source": "accepted"}), rows(board_width={"value": 61, "source": "guessed"}),
    rows(board_width={"source": "guessed"}), rows(guess={"value": 4}),
    rows(board_width={"ref": "other"}), rows(board_width={}), rows(strap={}),
    rows(strap={"value": 19, "source": "measured", "tolerance": None, "ref": "the person's calipers"}),
    body(*json.loads(BASE)["items"], item(name="new_row", value=5)), ""])
def test_her_edit_that_keeps_confirmed_numbers_or_says_their_new_source_is_accepted(text: str) -> None:
    assert edit_by(HER, text) == "accepted"


def test_the_persons_edit_of_a_confirmed_number_is_accepted() -> None:
    assert edit_by(ALANA, rows(board_width={"value": 61})) == "accepted"


def test_the_confirmed_check_runs_only_on_facts_pieces() -> None:
    note = Kind("note", "stored", "Note", 2000, "plain")
    rules = Rules({"facts": KIND, "note": note}, max_pieces=4, title_max_chars=20, recent_commands=10,
                  undo_window=50)
    made = replay([Add(ALANA, "note", Text("t", BASE), "medium"),
                   Edit(HER, 1, 1, Text("t", rows(board_width={"value": 61})))], rules)[-1]
    assert isinstance(made, Accepted)


def test_what_she_is_told_names_every_source_and_unit() -> None:
    hint = bench_results.HINTS["bad_facts"]
    for word in (*facts.SOURCES, *facts.UNITS):
        assert word in hint, word
    listed = bench_specs.INSTRUCTIONS.split("each row with its source:")[1].split(".")[0]
    for source in facts.SOURCES:
        assert source in listed, source
    assert "confirmed_measurement" in bench_results.HINTS
