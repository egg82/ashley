"""`ashley.workshop.measurements` from its docstring: which bodies are measurements, what `items_of` reads back, and that
`well_formed` and `items_of` never disagree."""

import json
import math
from typing import Any

import pytest
from ashley.workshop.measurements import MAX_REF, NAME, SOURCES, UNITS, Measurement, items_of, well_formed
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from measurements_blind_support import GOOD, body_of, good_bodies, item_lists, names, with_, without


def read(items: list[dict[str, Any]]) -> tuple[Measurement, ...]:
    got = items_of(body_of(items))
    assert got is not None
    numbers = tuple(m for m in got if isinstance(m, Measurement))
    assert len(numbers) == len(got)
    return numbers


# --- the constants ------------------------------------------------------------------------------------------------


def test_the_constants_are_the_documented_ones() -> None:
    assert MAX_REF == 200
    assert UNITS == {"mm", "deg", "count", "g", "ml", "min"}
    assert SOURCES == {"measured", "datasheet", "accepted", "bound", "guessed"}
    assert NAME.fullmatch("abc_9") and NAME.fullmatch("_x") and not NAME.fullmatch("9a")


# --- accepted shapes ----------------------------------------------------------------------------------------------


def test_an_empty_body_is_a_draft_that_passes_and_holds_nothing() -> None:
    assert well_formed("") is True
    assert items_of("") is None


def test_an_empty_list_passes_and_holds_no_measurements() -> None:
    assert well_formed('{"items": []}') is True
    assert items_of('{"items": []}') == ()


def test_one_item_reads_back_field_by_field() -> None:
    got = read([{"name": "bore", "value": 8, "unit": "mm", "source": "datasheet", "tolerance": 0.1, "ref": "p. 3"}])
    assert got == (Measurement("bore", 8.0, "mm", "datasheet", 0.1, "p. 3"),)
    assert isinstance(got[0].value, float)


def test_the_optional_keys_read_back_as_none_when_absent() -> None:
    (m,) = read([GOOD])
    assert (m.tolerance, m.ref) == (None, None)


@pytest.mark.parametrize("unit", ["mm", "deg", "count", "g", "ml", "min"])
@pytest.mark.parametrize("source", ["measured", "datasheet", "accepted", "bound", "guessed"])
def test_every_unit_and_source_is_accepted(unit: str, source: str) -> None:
    assert well_formed(body_of([with_(unit=unit, source=source, tolerance=0.5)]))


def test_a_zero_tolerance_and_negative_or_zero_values_are_accepted() -> None:
    assert well_formed(body_of([with_(tolerance=0), with_(name="b", value=0, tolerance=0.0), with_(name="c", value=-3.5)]))


def test_names_may_differ_only_in_case() -> None:
    assert well_formed(body_of([with_(name="Width"), with_(name="width")]))


def test_the_longest_name_is_accepted_and_one_more_is_refused() -> None:
    longest = max(k for k in range(1, 200) if NAME.fullmatch("a" * k))
    assert longest == 64
    assert well_formed(body_of([with_(name="a" * longest)]))
    assert not well_formed(body_of([with_(name="a" * (longest + 1))]))


def test_a_ref_of_exactly_the_limit_is_accepted_and_one_over_is_refused() -> None:
    assert well_formed(body_of([with_(ref="r" * MAX_REF)]))
    assert not well_formed(body_of([with_(ref="r" * (MAX_REF + 1))]))


def test_a_ref_is_counted_in_characters_not_bytes() -> None:
    assert well_formed(body_of([with_(ref="é" * MAX_REF)]))
    assert well_formed(body_of([with_(ref="\U0001f600" * MAX_REF)]))
    assert not well_formed(body_of([with_(ref="\U0001f600" * (MAX_REF + 1))]))


def test_the_exponent_form_of_a_number_is_a_number() -> None:
    assert read([with_(value=1e300)])[0].value == 1e300
    assert math.isclose(read([with_(value=-2.5e-7)])[0].value, -2.5e-7)


def test_whitespace_around_json_tokens_does_not_matter() -> None:
    assert well_formed('  {\n "items" : [ { "name" : "a", "value" : 1, "unit" : "mm", "source" : "guessed" } ] }\n')


# --- refused shapes -----------------------------------------------------------------------------------------------

REFUSED_BODIES: dict[str, str] = {
    "not json": "not measurements",
    "truncated": '{"items": [',
    "a list at top": "[]",
    "a string at top": '"items"',
    "null at top": "null",
    "a number at top": "3",
    "an empty object": "{}",
    "items is null": '{"items": null}',
    "items is an object": '{"items": {}}',
    "items is a string": '{"items": "x"}',
    "an extra top key": '{"items": [], "note": 1}',
    "a different top key": '{"item": []}',
    "an item that is a string": '{"items": ["width"]}',
    "an item that is null": '{"items": [null]}',
    "an item that is a list": '{"items": [[]]}',
    "an empty item": '{"items": [{}]}',
    "NaN": '{"items": [{"name": "a", "value": NaN, "unit": "mm", "source": "guessed"}]}',
    "Infinity": '{"items": [{"name": "a", "value": Infinity, "unit": "mm", "source": "guessed"}]}',
    "-Infinity": '{"items": [{"name": "a", "value": -Infinity, "unit": "mm", "source": "guessed"}]}',
    "a value that overflows a float": '{"items": [{"name": "a", "value": 1e999, "unit": "mm", "source": "guessed"}]}',
    "a huge integer value": '{"items": [{"name": "a", "value": 1' + "0" * 400 + ', "unit": "mm", "source": "guessed"}]}',
    "a tolerance that overflows": '{"items": [{"name": "a", "value": 1, "unit": "mm", "source": "guessed", "tolerance": 1e999}]}',
    "a NaN tolerance": '{"items": [{"name": "a", "value": 1, "unit": "mm", "source": "guessed", "tolerance": NaN}]}',
}

BAD_ITEMS: dict[str, dict[str, Any]] = {
    "a missing name": without("name"),
    "a missing value": without("value"),
    "a missing unit": without("unit"),
    "a missing source": without("source"),
    "an extra key": with_(colour="red"),
    "a key named note": with_(note="x"),
    "a key named id": with_(id=1),
    "a capitalised Name key": with_(Value=1),
    "a name starting with a digit": with_(name="9a"),
    "an empty name": with_(name=""),
    "a name with a hyphen": with_(name="a-b"),
    "a name with a space": with_(name="a b"),
    "a name with a trailing newline": with_(name="a\n"),
    "a name with a non-ASCII letter": with_(name="é"),
    "a name with a non-ASCII digit": with_(name="a٣"),
    "a name over the limit": with_(name="a" * 65),
    "a numeric name": with_(name=5),
    "a null name": with_(name=None),
    "a string value": with_(value="12"),
    "a null value": with_(value=None),
    "a boolean value": with_(value=True),
    "a list value": with_(value=[1]),
    "an unknown unit": with_(unit="cm"),
    "an upper-case unit": with_(unit="MM"),
    "an inch unit": with_(unit="in"),
    "an empty unit": with_(unit=""),
    "a null unit": with_(unit=None),
    "a numeric unit": with_(unit=1),
    "an unknown source": with_(source="estimated"),
    "an upper-case source": with_(source="Measured"),
    "an empty source": with_(source=""),
    "a null source": with_(source=None),
    "a negative tolerance": with_(tolerance=-0.1),
    "a string tolerance": with_(tolerance="0.1"),
    "a boolean tolerance": with_(tolerance=False),
    "a list tolerance": with_(tolerance=[]),
    "a ref over the limit": with_(ref="r" * (MAX_REF + 1)),
    "a numeric ref": with_(ref=5),
    "a list ref": with_(ref=["a"]),
    "a boolean ref": with_(ref=True),
}


@pytest.mark.parametrize("body", REFUSED_BODIES.values(), ids=REFUSED_BODIES.keys())
def test_a_body_outside_the_shape_is_refused(body: str) -> None:
    assert well_formed(body) is False
    assert items_of(body) is None


@pytest.mark.parametrize("bad", BAD_ITEMS.values(), ids=BAD_ITEMS.keys())
def test_an_item_outside_the_shape_is_refused_alone_and_among_good_ones(bad: dict[str, Any]) -> None:
    assert not well_formed(body_of([bad]))
    assert not well_formed(body_of([with_(name="ok1"), bad, with_(name="ok2")]))
    assert items_of(body_of([bad])) is None


def test_a_name_used_twice_is_refused_whatever_the_rest_of_the_items_say() -> None:
    assert not well_formed(body_of([with_(), with_()]))
    assert not well_formed(body_of([with_(unit="deg", source="guessed"), with_(value=99, tolerance=1, ref="x")]))
    assert not well_formed(body_of([with_(name="a"), with_(name="b"), with_(name="a")]))


def test_a_refused_body_is_refused_even_when_a_byte_order_mark_or_junk_follows_valid_json() -> None:
    assert not well_formed(body_of([GOOD]) + " trailing")
    assert not well_formed(body_of([GOOD]) + body_of([GOOD]))


# --- properties ---------------------------------------------------------------------------------------------------


@settings(max_examples=40)
@given(items=item_lists())
def test_a_well_formed_body_reads_back_what_was_written_in_order(items: list[dict[str, Any]]) -> None:
    body = body_of(items)
    assert well_formed(body)
    got = items_of(body)
    assert got == tuple(
        Measurement(i["name"], float(i["value"]), i["unit"], i["source"],
                    float(i["tolerance"]) if "tolerance" in i else None, i.get("ref"), i.get("asked", False))
        for i in items)


@settings(max_examples=40)
@given(items=item_lists(), indent=st.sampled_from([None, 0, 1, 4]))
def test_how_the_json_is_laid_out_does_not_change_what_it_holds(items: list[dict[str, Any]], indent: int | None) -> None:
    assert items_of(json.dumps({"items": items}, indent=indent)) == items_of(body_of(items))


@settings(max_examples=40)
@given(items=item_lists(min_size=1), data=st.data())
def test_reordering_the_items_reorders_the_result_the_same_way(items: list[dict[str, Any]], data: st.DataObject) -> None:
    shuffled = data.draw(st.permutations(items))
    assert items_of(body_of(shuffled)) == tuple(
        m for name in [i["name"] for i in shuffled] for m in read(items) if m.name == name)


@settings(max_examples=40)
@given(items=item_lists(min_size=1), data=st.data(), bad=st.sampled_from(list(BAD_ITEMS.values())))
def test_one_bad_item_anywhere_makes_the_whole_body_refused(
        items: list[dict[str, Any]], data: st.DataObject, bad: dict[str, Any]) -> None:
    at = data.draw(st.integers(0, len(items)))
    assert not well_formed(body_of([*items[:at], bad, *items[at:]]))


@settings(max_examples=40)
@given(items=item_lists(min_size=1), data=st.data())
def test_repeating_any_item_name_is_refused(items: list[dict[str, Any]], data: st.DataObject) -> None:
    dup = data.draw(st.sampled_from(items))
    assert not well_formed(body_of([*items, {**GOOD, "name": dup["name"]}]))


@settings(max_examples=40)
@given(items=item_lists(min_size=1), data=st.data(),
       key=st.sampled_from(["tolerance", "ref"]), junk=st.sampled_from([None, True, [], {}, "x"]))
def test_a_wrong_typed_optional_key_is_refused_unless_it_is_a_valid_ref(
        items: list[dict[str, Any]], data: st.DataObject, key: str, junk: object) -> None:
    at = data.draw(st.integers(0, len(items) - 1))
    changed = [{**i, key: junk} if n == at else i for n, i in enumerate(items)]
    assert well_formed(body_of(changed)) is (key == "ref" and junk == "x")


@settings(max_examples=40)
@given(body=st.text(max_size=60))
def test_the_two_functions_agree_on_any_text_and_never_raise(body: str) -> None:
    assume(body.strip() != "")
    ok = well_formed(body)
    assert ok is (body == "" or items_of(body) is not None)


JSONISH = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(-10**3, 10**3), st.floats(allow_nan=False, allow_infinity=False),
              st.text(max_size=6)),
    lambda children: st.one_of(st.lists(children, max_size=3), st.dictionaries(st.text(max_size=6), children, max_size=3)),
    max_leaves=12)


@settings(max_examples=300)
@given(doc=JSONISH)
def test_any_json_document_is_judged_consistently_and_only_an_items_object_passes(doc: Any) -> None:
    body = json.dumps(doc)
    ok = well_formed(body)
    assert ok is (items_of(body) is not None)
    if ok:
        parsed: Any = json.loads(body)
        assert list(parsed.keys()) == ["items"] and type(parsed["items"]) is list


@settings(max_examples=40)
@given(body=good_bodies)
def test_the_generator_of_good_bodies_agrees_with_the_validator(body: str) -> None:
    assert well_formed(body)


@given(extra=names.filter(lambda n: n not in {"name", "value", "unit", "source", "tolerance", "ref"}), junk=st.sampled_from([1, "x", None]))
def test_any_key_besides_the_six_is_refused(extra: str, junk: object) -> None:
    assert not well_formed(body_of([{**GOOD, extra: junk}]))


def test_a_long_list_reads_back_whole() -> None:
    items = [with_(name=f"n{i}", value=i) for i in range(700)]
    got = read(items)
    assert [m.name for m in got] == [f"n{i}" for i in range(700)]
