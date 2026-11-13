"""A model run's report (`ashley.workshop.model_report`): the script's `out/report.json` understood, each check's verdict
computed from its numbers and the source of the measurements it rests on; and the measurements file a model run starts with
(`ashley.workshop.measurements_file`)."""

import json
from typing import Any

import pytest
from ashley.runs.model import Outcome, Output
from ashley.workshop import measurements_file
from ashley.api.bench_report_models import report_of_wire
from ashley.tools.run_model import extras
from ashley.workshop.model_report import Check, Island, ModelReport, Overlap, Part, PrintCheck, PrintPart, holds, open_guesses, report_of

PART = {"name": "lid", "volume": 1200.5, "bbox": {"min": [0, 0, 0], "max": [40, 30, 10]}}


def check(name: Any = "clearance", actual: Any = 2.0, op: Any = ">=", target: Any = 1.5, tolerance: Any = 0.0,
          rests_on: Any = None) -> dict[str, Any]:
    return {"name": name, "actual": actual, "op": op, "target": target, "tolerance": tolerance,
            "rests_on": rests_on or []}


def report(checks: list[Any], **over: Any) -> dict[str, Any]:
    return {"unit": "mm", "parts": [PART], "triangles": 12, "checks": checks, **over}


def ran(body: object, outcome: Outcome = "ran", exit_code: int | None = 0) -> Output:
    text = body if isinstance(body, str) else json.dumps(body)
    return Output(outcome, exit_code, "", "", False, {"out/report.json": text}, ())


def measures(**sources: str) -> dict[str, str]:
    items = [{"name": n, "value": 1, "unit": "mm", "source": s, "tolerance": 0.5} for n, s in sources.items()]
    return {"measurements.json": json.dumps({"items": items})}


def test_a_report_is_its_parts_triangles_and_checks_with_a_verdict_each() -> None:
    got = report_of(ran(report([check(rests_on=["board"])])), measures(board="measured"))
    assert got == ModelReport("mm", (Part("lid", 1200.5, (0.0, 0.0, 0.0), (40.0, 30.0, 10.0)),), 12,
                              (Check("clearance", 2.0, ">=", 1.5, 0.0, ("board",), "pass"),))


@pytest.mark.parametrize("actual,op,target,tol,expected", [
    (2.0, ">=", 1.5, 0.0, True), (1.4, ">=", 1.5, 0.0, False), (1.4, ">=", 1.5, 0.1, True), (1.39, ">=", 1.5, 0.1, False),
    (3.0, "<=", 3.0, 0.0, True), (3.05, "<=", 3.0, 0.1, True), (3.2, "<=", 3.0, 0.1, False),
    (3.0, "<", 3.0, 0.0, False), (2.9, "<", 3.0, 0.0, True), (3.0, ">", 3.0, 0.0, False), (3.1, ">", 3.0, 0.0, True),
    (3.0, "==", 3.0, 0.0, True), (3.05, "==", 3.0, 0.1, True), (3.2, "==", 3.0, 0.1, False), (2.8, "==", 3.0, 0.1, False)])
def test_a_comparison_holds_with_its_tolerance_as_slack_in_the_direction_that_favours_it(
        actual: float, op: str, target: float, tol: float, expected: bool) -> None:
    assert holds(actual, op, target, tol) is expected


def test_a_failing_check_fails_whatever_it_rests_on() -> None:
    got = report_of(ran(report([check(actual=1.0, rests_on=["board"])])), measures(board="guessed"))
    assert got is not None and got.checks[0].verdict == "fail"


@pytest.mark.parametrize("source,verdict", [("measured", "pass"), ("datasheet", "pass"), ("accepted", "pass"),
                                            ("bound", "pass"), ("guessed", "unconfirmed")])
def test_a_passing_check_is_unconfirmed_when_a_measurement_it_rests_on_is_guessed(source: str, verdict: str) -> None:
    got = report_of(ran(report([check(rests_on=["a", "b"])])), measures(a="measured", b=source))
    assert got is not None and got.checks[0].verdict == verdict


def checks_of(output: Output, inputs: dict[str, str]) -> tuple[Check, ...]:
    got = report_of(output, inputs)
    assert got is not None
    return got.checks


def test_a_passing_check_resting_on_a_measurement_the_run_did_not_have_is_unconfirmed() -> None:
    assert checks_of(ran(report([check(rests_on=["gone"])])), measures(a="measured"))[0].verdict == "unconfirmed"
    assert checks_of(ran(report([check(rests_on=["a"])])), {})[0].verdict == "unconfirmed"


def test_a_check_resting_on_nothing_is_judged_by_its_numbers_alone() -> None:
    assert checks_of(ran(report([check()])), {})[0].verdict == "pass"


def test_only_a_run_that_ran_to_its_end_with_exit_zero_has_a_report() -> None:
    good = report([check()])
    assert report_of(ran(good, "timed_out", None), {}) is None
    assert report_of(ran(good, "ran", 1), {}) is None
    assert report_of(Output("ran", 0, "", "", False, {}, ()), {}) is None


@pytest.mark.parametrize("bad", [
    "not json", "[]", "{}", json.dumps(report([], unit="in")), json.dumps(report([], triangles=-1)),
    json.dumps(report([], triangles=1.5)), json.dumps(report([], triangles=True)), json.dumps(report([], parts={})),
    json.dumps(report([], parts=[{**PART, "volume": "big"}])), json.dumps(report([], parts=[{**PART, "bbox": {"min": [0, 0], "max": [1, 1, 1]}}])),
    json.dumps(report([], parts=[{**PART, "bbox": {"min": [0, 0, "x"], "max": [1, 1, 1]}}])),
    json.dumps(report([], parts=["lid"])), json.dumps(report([check(op="!=")])), json.dumps(report([check(tolerance=-1)])),
    json.dumps(report([check(actual="2")])), json.dumps(report([check(rests_on=[1])])), json.dumps(report(["c"])),
    '{"unit": "mm", "parts": [], "triangles": 1, "checks": [{"name": "x", "actual": NaN, "op": ">=", "target": 1, "tolerance": 0, "rests_on": []}]}',
])
def test_a_report_not_of_the_shape_the_helper_writes_is_none(bad: str) -> None:
    assert report_of(ran(bad), {}) is None


def test_a_report_with_no_parts_or_checks_is_still_a_report() -> None:
    assert report_of(ran(report([], parts=[])), {}) == ModelReport("mm", (), 12, ())


def body(*items: dict[str, Any]) -> str:
    return json.dumps({"items": list(items)})


def item(name: str, value: float = 1.0, **extra: Any) -> dict[str, Any]:
    return {"name": name, "value": value, "unit": "mm", "source": "measured", **extra}


def test_the_measurements_file_merges_the_pieces_in_order_keeping_a_repeated_names_first_value() -> None:
    text = measurements_file.file_of([body(item("a", 1, tolerance=0.1), item("b", 2)), "", body(item("b", 9), item("c", 3, ref="x"))])
    assert text is not None
    assert json.loads(text) == {"items": [item("a", 1, tolerance=0.1), item("b", 2), item("c", 3, ref="x")]}


def test_no_measurements_make_no_file() -> None:
    assert measurements_file.file_of([]) is None
    assert measurements_file.file_of(["", "not a body", body()]) is None


OVERLAP = {"a": "holder", "b": "block", "volume_mm3": 1600.0, "bbox": {"min": [-10, -10, -9], "max": [10, 10, -5]}}
APART = check("parts_apart:holder:block", actual=1600.0, op="==", target=0.0)


def test_overlaps_round_trip_with_the_failed_check_beside_them() -> None:
    got = report_of(ran(report([APART], overlaps=[OVERLAP], overlap_parts_skipped=2)), {})
    assert got is not None
    assert got.overlaps == (Overlap("holder", "block", 1600.0, (-10.0, -10.0, -9.0), (10.0, 10.0, -5.0)),)
    assert got.overlap_parts_skipped == 2
    assert [c.verdict for c in got.checks] == ["fail"]


def test_a_report_without_overlap_fields_has_none() -> None:
    got = report_of(ran(report([])), {})
    assert got is not None and (got.overlaps, got.overlap_parts_skipped) == ((), 0)


@pytest.mark.parametrize("bad", [
    {"overlaps": [{**OVERLAP, "volume_mm3": "big"}]}, {"overlaps": [{**OVERLAP, "a": 3}]},
    {"overlaps": [{**OVERLAP, "bbox": {"min": [0, 0], "max": [1, 1, 1]}}]}, {"overlaps": "none"}, {"overlap_parts_skipped": -1},
    {"overlap_parts_skipped": 1.5}])
def test_a_malformed_overlap_makes_the_whole_report_none(bad: dict[str, Any]) -> None:
    assert report_of(ran(report([], **bad)), {}) is None


def test_the_wire_and_her_tool_result_carry_the_overlaps_as_numbers() -> None:
    output = ran(report([APART], overlaps=[OVERLAP], overlap_parts_skipped=1))
    parsed = report_of(output, {})
    assert parsed is not None
    wire = report_of_wire(parsed)
    assert [(o.a, o.b, o.volume_mm3, o.bbox_min, o.bbox_max) for o in wire.overlaps] == [("holder", "block", 1600.0, [-10.0, -10.0, -9.0], [10.0, 10.0, -5.0])]
    assert wire.overlap_parts_skipped == 1
    told = extras((), output, {})["report"]
    assert isinstance(told, dict) and told["overlaps"][0]["volume_mm3"] == 1600.0


def test_the_open_guesses_are_the_guessed_numbers_an_unconfirmed_check_rests_on() -> None:
    inputs = measures(a="guessed", b="measured", c="guessed", d="guessed")
    out = ran(report([check(rests_on=["a", "b"]), check(rests_on=["c"], actual=0.5), check(rests_on=["b"])]))
    assert open_guesses(out, inputs) == {"a"}


def test_a_name_the_run_does_not_hold_or_a_run_with_no_report_has_no_open_guess() -> None:
    assert open_guesses(ran(report([check(rests_on=["gone"])])), measures(a="guessed")) == set()
    assert open_guesses(ran(report([check(rests_on=["a"])]), "failed", 1), measures(a="guessed")) == set()


# The `print` section and failed checks the CAD helper wrote for the gate block in deploy/cad/test_ashley_print.py
# (captured from a run in the CAD image), with the parts' roles.
ISLAND: dict[str, Any] = {"bbox": {"min": [-10.24, -9.0, -4.8], "max": [19.65, 6.01, -4.8]}, "area_mm2": 448.649,
                          "min_gap_mm": 0.4, "median_gap_mm": 1.2}
GATE_PART: dict[str, Any] = {
    "name": "gate_test_block", "bed_z": -6.0, "support_area_mm2": 1040.471, "bed_contact_mm2": 287.243, "fits_bed": None,
    "islands": [ISLAND, {"bbox": {"min": [-10.24, -9.9, 0.0], "max": [19.65, 9.9, 0.0]}, "area_mm2": 591.822,
                         "min_gap_mm": 4.0, "median_gap_mm": 4.0}],
    "islands_total": 2}
GATE_PRINT: dict[str, Any] = {"bed_fit_skipped": "no_bed", "parts": [GATE_PART]}
GATE_CHECKS = [check("print_gap:gate_test_block", actual=0.4, op=">=", target=0.6),
               check("print_trapped_support:gate_test_block", actual=1.2, op=">=", target=1.5)]
GATE = report(GATE_CHECKS, parts=[{**PART, "name": "gate_test_block", "role": "flexure"}], print=GATE_PRINT)


def test_the_print_section_round_trips_with_its_failed_checks_and_the_parts_roles() -> None:
    got = report_of(ran(GATE), {})
    assert got is not None and got.print is not None
    assert [(p.name, p.role) for p in got.parts] == [("gate_test_block", "flexure")]
    assert [(c.name, c.actual, c.verdict) for c in got.checks] == [
        ("print_gap:gate_test_block", 0.4, "fail"), ("print_trapped_support:gate_test_block", 1.2, "fail")]
    assert (got.print.skip_reason, got.print.bed_fit_skipped, got.print.max_triangles) == (None, "no_bed", None)
    (part,) = got.print.printed
    assert (part.name, part.bed_z, part.support_area_mm2, part.bed_contact_mm2, part.fits_bed, part.islands_total) == (
        "gate_test_block", -6.0, 1040.471, 287.243, None, 2)
    assert part.islands[0] == Island((-10.24, -9.0, -4.8), (19.65, 6.01, -4.8), 448.649, 0.4, 1.2)


def test_a_part_without_a_role_is_unknown_and_a_report_without_print_has_none() -> None:
    got = report_of(ran(report([])), {})
    assert got is not None and got.parts[0].role == "unknown" and got.print is None


SECTIONS: list[tuple[dict[str, Any], PrintCheck]] = [
    ({"skipped": "no_settings"}, PrintCheck("no_settings")),
    ({"skipped": "no_printed_parts"}, PrintCheck("no_printed_parts")),
    ({"skipped": "too_many_triangles", "triangles": 300000, "max_triangles": 200000},
     PrintCheck("too_many_triangles", max_triangles=200000)),
    ({"bed_fit_skipped": None, "parts": [{**GATE_PART, "fits_bed": True, "islands": [], "islands_total": 0}]},
     PrintCheck(None, (PrintPart("gate_test_block", -6.0, 1040.471, 287.243, True, (), 0),))),
]


@pytest.mark.parametrize("section,expected", SECTIONS)
def test_a_skipped_print_check_carries_its_reason_and_a_bed_fit_its_answer(section: dict[str, Any],
                                                                            expected: PrintCheck) -> None:
    got = report_of(ran(report([], print=section)), {})
    assert got is not None and got.print == expected


def gate_part(**over: Any) -> dict[str, Any]:
    return {"parts": [{**GATE_PART, **over}]}


@pytest.mark.parametrize("bad", [
    {"role": 3}, {"print": "none"}, {"print": {"skipped": "tired"}}, {"print": {"skipped": "too_many_triangles", "max_triangles": -1}},
    {"print": {"parts": "all"}}, {"print": {**GATE_PRINT, "bed_fit_skipped": "small"}},
    {"print": gate_part(support_area_mm2="lots")}, {"print": gate_part(fits_bed="yes")}, {"print": gate_part(islands_total=1)},
    {"print": gate_part(islands=[{**ISLAND, "min_gap_mm": None}])},
    {"print": gate_part(islands=[{**ISLAND, "bbox": {"min": [0, 0], "max": [1, 1, 1]}}])}, {"print": gate_part(name=7)}, {"print": gate_part(bed_z=None)},
])
def test_a_malformed_role_or_print_section_makes_the_whole_report_none(bad: dict[str, Any]) -> None:
    if "role" in bad:
        body = report([], parts=[{**PART, **bad}])
    else:
        body = report([], **bad)
    assert report_of(ran(body), {}) is None


def test_the_wire_and_her_tool_result_carry_roles_and_the_print_section_as_numbers() -> None:
    output = ran(GATE)
    parsed = report_of(output, {})
    assert parsed is not None
    wire = report_of_wire(parsed)
    assert wire.parts[0].role == "flexure"
    assert wire.print is not None and wire.print.bed_fit_skipped == "no_bed"
    island = wire.print.printed[0].islands[0]
    assert (island.bbox_min, island.min_gap_mm, island.median_gap_mm) == ([-10.24, -9.0, -4.8], 0.4, 1.2)
    assert wire.print.printed[0].bed_z == -6.0
    told = extras((), output, {})["report"]
    assert isinstance(told, dict)
    assert told["parts"][0]["role"] == "flexure" and told["print"]["printed"][0]["support_area_mm2"] == 1040.471
    skipped = report_of_wire(ModelReport("mm", (), 0, (), print=PrintCheck("no_settings")))
    assert skipped.print is not None and (skipped.print.skip_reason, skipped.print.printed) == ("no_settings", [])
