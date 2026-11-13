"""What a choice row does downstream of the facts piece (design sections 1 and 2): `confirmed` for each source
as the report reads it, a check resting on a guessed choice is `unconfirmed`, the model file carries choice rows, the
parts of a report carry the form of a reference part, and the moment layer carries a guessed choice as still open."""

import json
from typing import Any

import pytest
from ashley.runs.model import Output
from ashley.tools.bench_now import now, open_rows
from ashley.workshop import facts_file
from ashley.workshop.model import Bench, Piece, Place, Text
from ashley.workshop.model_report import report_of
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import BenchView
from bench_tools_support import EPOCH
from facts_blind_support import CHOICE_SOURCES, NUMBER, body_of, choice, cited

PART = {"name": "strap", "volume": 1200.5, "bbox": {"min": [0, 0, 0], "max": [40, 30, 10]}}


def check(rests_on: list[str], actual: float = 2.0) -> dict[str, Any]:
    return {"name": "fit", "actual": actual, "op": ">=", "target": 1.5, "tolerance": 0.0, "rests_on": rests_on}


def ran(checks: list[Any], **part: Any) -> Output:
    report = {"unit": "mm", "parts": [{**PART, **part}], "triangles": 12, "checks": checks}
    return Output("ran", 0, "", "", False, {"out/report.json": json.dumps(report)}, ())


def inputs(*rows: dict[str, Any]) -> dict[str, str]:
    """The run's inputs as the app builds them from a facts piece holding `rows`."""
    return {"facts.json": facts_file.file_of([body_of(*rows)]) or ""}


def verdict(rests_on: list[str], *rows: dict[str, Any]) -> str:
    got = report_of(ran([check(rests_on)]), inputs(*rows))
    assert got is not None
    return got.checks[0].verdict


# --- confirmed, by source -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", [s for s in CHOICE_SOURCES if s != "guessed"])
def test_a_check_resting_on_a_confirmed_choice_passes(source: str) -> None:
    assert verdict(["lanyard_form"], cited(source)) == "pass"


def test_a_check_resting_on_a_guessed_choice_is_unconfirmed() -> None:
    assert verdict(["lanyard_form"], choice()) == "unconfirmed"


def test_a_check_resting_on_a_stated_choice_and_a_guessed_one_is_unconfirmed() -> None:
    assert verdict(["lanyard_form", "other_form"], cited("stated"), choice(name="other_form")) == "unconfirmed"


def test_a_check_resting_on_a_measured_number_and_a_guessed_choice_is_unconfirmed() -> None:
    assert verdict(["width", "lanyard_form"], NUMBER, choice()) == "unconfirmed"


def test_a_check_resting_on_a_measured_number_and_a_stated_choice_passes() -> None:
    assert verdict(["width", "lanyard_form"], NUMBER, cited("stated")) == "pass"


def test_a_check_resting_on_a_choice_the_bench_does_not_hold_is_unconfirmed() -> None:
    assert verdict(["lanyard_form"], NUMBER) == "unconfirmed"


def test_a_failing_check_fails_whatever_its_choice_is() -> None:
    got = report_of(ran([check(["lanyard_form"], actual=1.0)]), inputs(cited("stated")))
    assert got is not None and got.checks[0].verdict == "fail"


def test_a_report_with_no_choice_rows_reads_as_it_did() -> None:
    assert verdict(["width"], NUMBER) == "pass"
    assert verdict(["width"], {**NUMBER, "source": "guessed"}) == "unconfirmed"


# --- the form of a reference part is carried by the report -----------------------------------------------------------


def test_a_part_naming_its_form_is_carried_in_the_report() -> None:
    got = report_of(ran([], role="reference", form="lanyard_form"), inputs(cited("stated")))
    assert got is not None
    assert getattr(got.parts[0], "form") == "lanyard_form"


# --- the file a model run starts with --------------------------------------------------------------------------------


def test_the_model_file_carries_choice_rows() -> None:
    row = cited("stated", options=["flat woven strap", "round cord"])
    given = {**NUMBER, "name": "strap_width", "source": "guessed", "given": "lanyard_form"}
    text = facts_file.file_of([body_of(row, given)])
    assert text is not None
    items = {i["name"]: i for i in json.loads(text)["items"]}
    assert items["lanyard_form"]["kind"] == "choice"
    assert items["lanyard_form"]["value"] == "flat woven strap"
    assert items["lanyard_form"]["source"] == "stated"
    assert items["strap_width"]["given"] == "lanyard_form"
    assert items["strap_width"]["value"] == 12.5


def test_a_number_only_model_file_is_unchanged() -> None:
    text = facts_file.file_of([body_of(NUMBER)])
    assert text == '{"items":[{"name":"width","value":12.5,"unit":"mm","source":"measured"}]}'


def test_a_name_a_later_piece_repeats_keeps_its_first_row_across_kinds() -> None:
    text = facts_file.file_of([body_of(choice()), body_of(choice(value="round cord"))])
    assert text is not None
    assert [i["value"] for i in json.loads(text)["items"]] == ["flat woven strap"]


# --- still open in the moment layer ---------------------------------------------------------------------------------

RULES = Rules({"note": Kind("note", "stored", "Note", 4000),
               "facts": Kind("facts", "stored", "Facts", 50000, "facts")},
              max_pieces=10, title_max_chars=40, recent_commands=5, undo_window=100)


def bench_of(body: str, outside: bool = False) -> BenchView:
    piece = Piece(1, "facts", Text("t", body), 1, Place(0, "medium"), 1, outside)
    return BenchView(Bench(9, 10, 1, "Lanyard", EPOCH, None), (piece,), ())


def test_a_guessed_choice_is_still_open_and_a_stated_one_is_not() -> None:
    view = bench_of(body_of(choice(), cited("stated", name="oven_kind", label="The oven", value="gas")))
    assert [r["name"] for r in open_rows(view, RULES)] == ["lanyard_form"]
    text = now(view, RULES, 2000)
    assert "lanyard_form" in text.split("Still open")[-1]


def test_a_guessed_choice_on_a_piece_written_after_outside_words_is_not_listed() -> None:
    assert open_rows(bench_of(body_of(choice()), outside=True), RULES) == []
