"""`model_report`: a run's `out/report.json` understood, each check judged here from its numbers and the source of the
facts it rests on. A passing check on a guess or a missing measurement is `unconfirmed`; a failing one stays
`fail`; a report not of the shape the helper writes is none, never partial."""

import json
from collections.abc import Mapping, Sequence

import pytest
from ashley.runs.model import Output
from ashley.workshop.facts_file import file_of
from ashley.workshop.model_report import ModelReport, holds, report_of
from run_artifacts_support import REPORT_NAME, check_json, measurement, facts_body, model_output, part_json, report_json


def inputs(*items: Mapping[str, object]) -> dict[str, str]:
    return {"facts.json": facts_body(*items)}


def verdicts(checks: Sequence[Mapping[str, object]], given: Mapping[str, str]) -> list[str]:
    report = report_of(model_output(report_json(*checks)), given)
    assert report is not None
    return [c.verdict for c in report.checks]


@pytest.mark.parametrize(("actual", "op", "target", "tol", "expected"), [
    (10.0, "==", 10.0, 0.0, True), (10.4, "==", 10.0, 0.5, True), (9.6, "==", 10.0, 0.5, True),
    (10.6, "==", 10.0, 0.5, False), (9.4, "==", 10.0, 0.5, False), (10.1, "==", 10.0, 0.0, False),
    (10.0, "<=", 10.0, 0.0, True), (10.5, "<=", 10.0, 0.5, True), (10.6, "<=", 10.0, 0.5, False),
    (5.0, "<=", 10.0, 0.0, True), (10.1, "<=", 10.0, 0.0, False),
    (10.0, ">=", 10.0, 0.0, True), (9.5, ">=", 10.0, 0.5, True), (9.4, ">=", 10.0, 0.5, False),
    (20.0, ">=", 10.0, 0.0, True), (9.9, ">=", 10.0, 0.0, False),
    (9.9, "<", 10.0, 0.0, True), (10.0, "<", 10.0, 0.0, False), (10.4, "<", 10.0, 0.5, True), (10.6, "<", 10.0, 0.5, False),
    (10.1, ">", 10.0, 0.0, True), (10.0, ">", 10.0, 0.0, False), (9.6, ">", 10.0, 0.5, True), (9.4, ">", 10.0, 0.5, False),
])
def test_a_comparison_holds_with_the_slack_in_the_direction_that_favours_it(
        actual: float, op: str, target: float, tol: float, expected: bool) -> None:
    assert holds(actual, op, target, tol) is expected


def test_the_report_is_read_into_its_parts_triangles_and_checks() -> None:
    report = report_of(model_output(report_json(
        check_json("fit", 2.0, ">=", 1.5, 0.25, ["w"]), parts=[part_json("lid"), part_json("base")], triangles=96)),
        inputs(measurement("w", 30)))
    assert isinstance(report, ModelReport)
    assert report.unit == "mm" and report.triangles == 96
    assert [(p.name, p.volume, p.bbox_min, p.bbox_max) for p in report.parts] == [
        ("lid", 6000.0, (0.0, 0.0, 0.0), (20.0, 30.0, 10.0)), ("base", 6000.0, (0.0, 0.0, 0.0), (20.0, 30.0, 10.0))]
    [c] = report.checks
    assert (c.name, c.actual, c.op, c.target, c.tolerance, tuple(c.rests_on), c.verdict) == (
        "fit", 2.0, ">=", 1.5, 0.25, ("w",), "pass")


def test_whole_numbers_in_a_report_are_numbers() -> None:
    text = json.dumps({"unit": "mm", "parts": [{"name": "p", "volume": 6000, "bbox": {"min": [0, 0, 0], "max": [1, 2, 3]}}],
                       "triangles": 12, "checks": [{"name": "c", "actual": 2, "op": ">=", "target": 1, "tolerance": 0,
                                                    "rests_on": []}]})
    report = report_of(model_output(text), {})
    assert report is not None and report.checks[0].verdict == "pass"


@pytest.mark.parametrize(("source", "verdict"), [("measured", "pass"), ("datasheet", "pass"), ("guessed", "unconfirmed")])
def test_a_check_that_holds_is_confirmed_by_the_source_it_rests_on(source: str, verdict: str) -> None:
    assert verdicts([check_json(rests_on=["w"])], inputs(measurement("w", 30, source))) == [verdict]


def test_a_check_that_holds_on_a_measurement_the_run_does_not_have_is_unconfirmed() -> None:
    assert verdicts([check_json(rests_on=["gone"])], inputs(measurement("w", 30))) == ["unconfirmed"]


def test_a_check_that_holds_with_no_facts_file_at_all_is_unconfirmed() -> None:
    assert verdicts([check_json(rests_on=["w"])], {}) == ["unconfirmed"]


def test_a_check_resting_on_nothing_is_judged_by_its_numbers_alone() -> None:
    assert verdicts([check_json(rests_on=[])], {}) == ["pass"]
    assert verdicts([check_json(actual=1.0, rests_on=[])], {}) == ["fail"]


def test_one_guess_among_the_facts_a_check_rests_on_leaves_it_unconfirmed() -> None:
    given = inputs(measurement("a", 1), measurement("b", 2, "guessed"), measurement("c", 3, "datasheet"))
    assert verdicts([check_json(rests_on=["a", "c"]), check_json(rests_on=["a", "b", "c"]),
                     check_json(rests_on=["a", "nope"])], given) == ["pass", "unconfirmed", "unconfirmed"]


@pytest.mark.parametrize("source", ["measured", "datasheet", "guessed"])
def test_a_check_that_fails_stays_fail_whatever_it_rests_on(source: str) -> None:
    given = inputs(measurement("w", 30, source))
    assert verdicts([check_json(actual=1.0, rests_on=["w"]), check_json(actual=1.0, rests_on=["gone"])], given) == ["fail", "fail"]


def test_a_failing_check_stays_fail_when_there_are_no_facts_at_all() -> None:
    assert verdicts([check_json(actual=1.0, rests_on=["w"])], {}) == ["fail"]


def test_the_tolerance_decides_the_verdict() -> None:
    given = inputs(measurement("w", 30))
    assert verdicts([check_json(actual=1.4, tolerance=0.2, rests_on=["w"]),
                     check_json(actual=1.4, tolerance=0.0, rests_on=["w"])], given) == ["pass", "fail"]


@pytest.mark.parametrize("claim", [{"verdict": "pass"}, {"pass": True}, {"passed": True}, {"ok": True}, {"status": "pass"}])
def test_a_pass_the_script_printed_is_not_believed(claim: Mapping[str, object]) -> None:
    given = inputs(measurement("w", 30))
    assert verdicts([{**check_json(actual=1.0, rests_on=["w"]), **claim}], given) == ["fail"]


def test_each_check_is_judged_on_its_own_numbers() -> None:
    given = inputs(measurement("a", 1), measurement("b", 2, "guessed"))
    got = verdicts([check_json("one", rests_on=["a"]), check_json("two", actual=0.0, rests_on=["a"]),
                    check_json("three", rests_on=["b"])], given)
    assert got == ["pass", "fail", "unconfirmed"]


def test_facts_that_cannot_be_read_confirm_nothing() -> None:
    assert verdicts([check_json(rests_on=["w"])], {"facts.json": "not json"}) == ["unconfirmed"]


def test_a_report_with_no_checks_is_a_report() -> None:
    report = report_of(model_output(report_json()), {})
    assert report is not None and report.checks == ()


@pytest.mark.parametrize("output", [
    Output("timed_out", None, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("failed", None, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("out_of_memory", None, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("unknown", None, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("ran", 1, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("ran", -9, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("timed_out", 0, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("failed", 0, "", "", False, {REPORT_NAME: report_json()}, ()),
    Output("ran", 0, "", "", False, {}, ()),
    Output("ran", 0, "", "", False, {"report.json": report_json()}, ()),
    Output("ran", 0, "", "", False, {}, (REPORT_NAME,)),
], ids=["timed_out", "failed", "oom", "unknown", "exit 1", "signal", "timed out with 0", "failed with 0", "no file",
         "wrong name", "file left out"])
def test_a_run_that_did_not_end_well_or_left_no_report_has_none(output: Output) -> None:
    assert report_of(output, {}) is None


GOOD_PART = part_json()
GOOD_CHECK = check_json()
BROKEN: dict[str, str] = {
    "not json": "{",
    "empty": "",
    "a list": "[]",
    "null": "null",
    "no checks key": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1}),
    "checks not a list": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1, "checks": {}}),
    "no parts key": json.dumps({"unit": "mm", "triangles": 1, "checks": []}),
    "no triangles": json.dumps({"unit": "mm", "parts": [GOOD_PART], "checks": []}),
    "no unit": json.dumps({"parts": [GOOD_PART], "triangles": 1, "checks": []}),
    "triangles a string": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": "12", "checks": []}),
    "a check without a target": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                            "checks": [{k: v for k, v in GOOD_CHECK.items() if k != "target"}]}),
    "a check without rests_on": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                            "checks": [{k: v for k, v in GOOD_CHECK.items() if k != "rests_on"}]}),
    "a check actual a string": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                           "checks": [{**GOOD_CHECK, "actual": "2.0"}]}),
    "a check with an unknown op": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                              "checks": [{**GOOD_CHECK, "op": "!="}]}),
    "infinite actual": '{"unit": "mm", "parts": [], "triangles": 1, "checks": [{"name": "c", "actual": Infinity, "op": ">=", '
                       '"target": 1, "tolerance": 0, "rests_on": []}]}',
    "nan target": '{"unit": "mm", "parts": [], "triangles": 1, "checks": [{"name": "c", "actual": 1, "op": ">=", '
                  '"target": NaN, "tolerance": 0, "rests_on": []}]}',
    "a boolean actual": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                    "checks": [{**GOOD_CHECK, "actual": True}]}),
    "negative triangles": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": -1, "checks": []}),
    "another unit": json.dumps({"unit": "in", "parts": [GOOD_PART], "triangles": 1, "checks": []}),
    "a negative tolerance": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                        "checks": [{**GOOD_CHECK, "tolerance": -1}]}),
    "a check that is not an object": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1, "checks": [5]}),
    "rests_on not a list of names": json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                                                "checks": [{**GOOD_CHECK, "rests_on": [1]}]}),
    "a part without a volume": json.dumps({"unit": "mm", "parts": [{k: v for k, v in GOOD_PART.items() if k != "volume"}],
                                           "triangles": 1, "checks": []}),
    "a bbox of two numbers": json.dumps({"unit": "mm", "parts": [{**GOOD_PART, "bbox": {"min": [0, 0], "max": [1, 2, 3]}}], "triangles": 1,
                                         "checks": []}),
}


@pytest.mark.parametrize("what", list(BROKEN))
def test_a_report_not_of_the_shape_the_helper_writes_is_none(what: str) -> None:
    assert report_of(model_output(BROKEN[what]), inputs(measurement("w", 1))) is None


def test_one_broken_check_among_good_ones_makes_the_whole_report_none() -> None:
    text = json.dumps({"unit": "mm", "parts": [GOOD_PART], "triangles": 1,
                       "checks": [GOOD_CHECK, {**GOOD_CHECK, "actual": "x"}, GOOD_CHECK]})
    assert report_of(model_output(text), {}) is None


def test_no_facts_means_no_file_and_so_does_a_body_with_no_item() -> None:
    assert file_of([]) is None
    assert file_of([facts_body()]) is None
    assert file_of([facts_body(), facts_body()]) is None


def test_facts_pieces_are_merged_in_order_each_item_as_it_was_written() -> None:
    first = {**measurement("w", 30), "tolerance": 0.1, "ref": "caliper"}
    second = measurement("d", 4, "datasheet")
    third = measurement("h", 90, "guessed", "deg")
    text = file_of([facts_body(first, second), facts_body(third)])
    assert text is not None and json.loads(text) == {"items": [first, second, third]}


def test_a_name_a_later_piece_repeats_keeps_its_first_value() -> None:
    text = file_of([facts_body(measurement("w", 30, "measured")), facts_body(measurement("w", 99, "guessed"),
                                                                                           measurement("x", 1))])
    assert text is not None
    assert json.loads(text)["items"] == [measurement("w", 30, "measured"), measurement("x", 1)]


def test_a_merged_file_confirms_a_check_the_same_way() -> None:
    text = file_of([facts_body(measurement("w", 30)), facts_body(measurement("w", 5, "guessed"))])
    assert text is not None
    assert verdicts([check_json(rests_on=["w"])], {"facts.json": text}) == ["pass"]
