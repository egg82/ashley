"""Blind contract tests of the CAD helper's choices (design section 2), run in the CAD image beside test_ashley_cad:

    podman run --rm --read-only --network=none --user 65534 --tmpfs /work:rw,mode=1777 -w /work \
      -v $PWD/test_ashley_cad.py:/test/test_ashley_cad.py:ro -v $PWD/test_ashley_facts_blind.py:/test/test_ashley_facts_blind.py:ro \
      -v $PWD/test_ashley_print.py:/test/test_ashley_print.py:ro -v $PWD/../../app/tests/cad_models:/test/models:ro \
      -v $PWD/../../app/ashley/workshop/print.json:/test/print.json:ro localhost/ashley-cad:test python -m unittest discover -v -s /test

`chosen(name)` returns a choice row's value and records the read; a `reference` part names its form, and a reference
part without one fails the run; `parts_apart` against a reference part rests on its form."""

import json
import re
import unittest
from pathlib import Path
from typing import Any

from test_ashley_cad import run

FORM = {"name": "lanyard_form", "kind": "choice", "value": "flat woven strap", "source": "stated"}
OTHER = {"name": "oven_kind", "kind": "choice", "value": "gas", "source": "guessed"}
WIDTH = {"name": "strap_width", "value": 20.0, "unit": "mm", "source": "guessed", "given": "lanyard_form"}
BOARD = {"name": "board_width", "value": 60.0, "unit": "mm", "source": "measured"}
FACTS = {"items": [FORM, OTHER, WIDTH, BOARD]}
NUMBERS = {"items": [BOARD]}
"""A file with no choice row: the controls that must pass today run on it."""

HEAD = """
from build123d import Box, Pos
from ashley_cad import check, measured, show
"""


def go(script: str, facts: dict[str, Any] | None = FACTS) -> tuple[int, str, dict[str, Any] | None, Path]:
    """Return code, stderr, the report (None when none was written) and the out directory of a run of `script`."""
    done, out = run(HEAD + script, measurements=facts)
    report = out / "report.json"
    return done.returncode, done.stderr, json.loads(report.read_text()) if report.is_file() else None, out


def failure(stderr: str) -> str:
    """The exception line a failed run ended with, which is what the script's author reads."""
    raised = [line for line in stderr.splitlines() if re.match(r"\w+(Error|Exception): ", line)]
    assert raised, f"no exception line in {stderr!r}"
    return raised[-1]


def checks(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    assert report is not None
    return {c["name"]: c for c in report["checks"]}


class Chosen(unittest.TestCase):
    def test_chosen_returns_the_value_of_the_choice(self) -> None:
        code, err, report, _ = go('''
from ashley_cad import chosen
assert chosen("lanyard_form") == "flat woven strap"
assert chosen("oven_kind") == "gas"
show(Box(1, 1, 1))
''')
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(report)

    def test_chosen_of_a_name_the_bench_does_not_hold_fails_the_run(self) -> None:
        code, _, report, _ = go('from ashley_cad import chosen\nchosen("nope")\nshow(Box(1, 1, 1))')
        self.assertNotEqual(code, 0)
        self.assertIsNone(report)

    def test_chosen_of_a_number_row_fails_the_run(self) -> None:
        code, _, report, _ = go('from ashley_cad import chosen\nchosen("board_width")\nshow(Box(1, 1, 1))')
        self.assertNotEqual(code, 0)
        self.assertIsNone(report)

    def test_chosen_with_no_measurements_file_fails_the_run(self) -> None:
        code, _, _, _ = go('from ashley_cad import chosen\nchosen("lanyard_form")\nshow(Box(1, 1, 1))', facts=None)
        self.assertNotEqual(code, 0)

    def test_a_check_without_rests_on_rests_on_the_choice_read(self) -> None:
        _, _, report, _ = go('''\nfrom ashley_cad import chosen
chosen("lanyard_form")
check("fit", 1.0, "==", 1.0)
show(Box(1, 1, 1))
''')
        self.assertEqual(checks(report)["fit"]["rests_on"], ["lanyard_form"])

    def test_a_check_without_rests_on_rests_on_every_read_in_order(self) -> None:
        _, _, report, _ = go('''\nfrom ashley_cad import chosen
measured("board_width")
chosen("oven_kind")
check("fit", 1.0, "==", 1.0)
show(Box(1, 1, 1))
''')
        self.assertEqual(checks(report)["fit"]["rests_on"], ["board_width", "oven_kind"])

    def test_a_choice_not_read_is_not_rested_on(self) -> None:
        _, _, report, _ = go('''
measured("board_width")
check("fit", 1.0, "==", 1.0)
show(Box(1, 1, 1))
''')
        self.assertEqual(checks(report)["fit"]["rests_on"], ["board_width"])

    def test_rests_on_may_name_a_choice(self) -> None:
        code, err, report, _ = go('check("fit", 1.0, "==", 1.0, rests_on=["lanyard_form"])\nshow(Box(1, 1, 1))')
        self.assertEqual(code, 0, err)
        self.assertEqual(checks(report)["fit"]["rests_on"], ["lanyard_form"])

    def test_measured_of_a_row_with_given_also_records_the_choice_it_names(self) -> None:
        _, _, report, _ = go('''
measured("strap_width")
check("fit", 1.0, "==", 1.0)
show(Box(1, 1, 1))
''')
        self.assertEqual(sorted(checks(report)["fit"]["rests_on"]), ["lanyard_form", "strap_width"])

    def test_a_number_without_given_records_only_itself(self) -> None:
        _, _, report, _ = go('''
measured("board_width")
check("fit", 1.0, "==", 1.0)
show(Box(1, 1, 1))
''', NUMBERS)
        self.assertEqual(checks(report)["fit"]["rests_on"], ["board_width"])

    def test_the_choice_is_recorded_once_however_often_it_is_read(self) -> None:
        _, _, report, _ = go('''\nfrom ashley_cad import chosen
chosen("lanyard_form")
measured("strap_width")
chosen("lanyard_form")
check("fit", 1.0, "==", 1.0)
show(Box(1, 1, 1))
''')
        self.assertEqual(sorted(checks(report)["fit"]["rests_on"]), ["lanyard_form", "strap_width"])


class ReferenceForms(unittest.TestCase):
    def test_a_reference_part_naming_its_form_runs_and_the_report_carries_the_form(self) -> None:
        code, err, report, _ = go('show(("strap", Box(20, 4, 2), "reference", "lanyard_form"), ("lid", Pos(60, 0, 0) * Box(10, 10, 2)))')
        self.assertEqual(code, 0, err)
        assert report is not None
        parts = {p["name"]: p for p in report["parts"]}
        self.assertEqual((parts["strap"]["role"], parts["strap"]["form"]), ("reference", "lanyard_form"))

    def test_a_reference_part_with_no_form_fails_the_run(self) -> None:
        code, err, report, out = go('show(("strap", Box(20, 4, 2), "reference"))')
        self.assertNotEqual(code, 0)
        self.assertIsNone(report)
        self.assertIn("form", failure(err))
        self.assertEqual(sorted(p.name for p in out.glob("*")) if out.is_dir() else [], [])

    def test_the_failure_names_the_part(self) -> None:
        _, err, _, _ = go('show(("strap", Box(20, 4, 2), "reference"))')
        self.assertIn("strap", failure(err))

    def test_a_reference_part_naming_a_number_row_fails_the_run(self) -> None:
        code, _, report, out = go('show(("strap", Box(20, 4, 2), "reference", "board_width"))')
        self.assertNotEqual(code, 0)
        self.assertIsNone(report)
        self.assertEqual(sorted(p.name for p in out.glob("*")) if out.is_dir() else [], [])

    def test_a_reference_part_naming_a_row_the_bench_does_not_hold_fails_the_run(self) -> None:
        code, _, report, _ = go('show(("strap", Box(20, 4, 2), "reference", "nope"))')
        self.assertNotEqual(code, 0)
        self.assertIsNone(report)

    def test_a_reference_part_naming_a_form_with_no_measurements_file_fails_the_run(self) -> None:
        code, _, _, _ = go('show(("strap", Box(20, 4, 2), "reference", "lanyard_form"))', facts=None)
        self.assertNotEqual(code, 0)

    def test_a_part_with_another_role_runs_as_before(self) -> None:
        code, err, report, _ = go('show(("lid", Box(10, 10, 2), "enclosure"))', NUMBERS)
        self.assertEqual(code, 0, err)
        assert report is not None
        self.assertEqual(report["parts"][0]["role"], "enclosure")

    def test_a_part_with_a_bad_role_still_fails_the_run(self) -> None:
        code, _, _, _ = go('show(("lid", Box(10, 10, 2), "gizmo"))')
        self.assertNotEqual(code, 0)


class ApartRestsOnForm(unittest.TestCase):
    OVERLAP = '''
show(("strap", Box(20, 20, 20), "reference", "lanyard_form"), ("lid", Pos(10, 0, 0) * Box(20, 20, 20)))
'''

    def test_an_overlap_with_a_reference_rests_on_its_form(self) -> None:
        _, _, report, _ = go(self.OVERLAP)
        self.assertEqual(checks(report)["parts_apart:strap:lid"]["rests_on"], ["lanyard_form"])

    def test_the_overlap_is_still_listed_and_the_check_still_fails_on_volume(self) -> None:
        _, _, report, _ = go(self.OVERLAP)
        assert report is not None
        self.assertEqual(len(report["overlaps"]), 1)
        self.assertGreater(checks(report)["parts_apart:strap:lid"]["actual"], 0)

    def test_the_form_is_rested_on_whichever_side_the_reference_is(self) -> None:
        _, _, report, _ = go('show(("lid", Pos(10, 0, 0) * Box(20, 20, 20)), ("strap", Box(20, 20, 20), "reference", "lanyard_form"))')
        self.assertEqual(checks(report)["parts_apart:lid:strap"]["rests_on"], ["lanyard_form"])

    def test_two_references_rest_on_both_their_forms(self) -> None:
        _, _, report, _ = go('show(("a", Box(20, 20, 20), "reference", "lanyard_form"), '
                             '("b", Pos(10, 0, 0) * Box(20, 20, 20), "reference", "oven_kind"))')
        self.assertEqual(sorted(checks(report)["parts_apart:a:b"]["rests_on"]), ["lanyard_form", "oven_kind"])

    def test_two_references_of_one_form_rest_on_it_once(self) -> None:
        _, _, report, _ = go('show(("a", Box(20, 20, 20), "reference", "lanyard_form"), '
                             '("b", Pos(10, 0, 0) * Box(20, 20, 20), "reference", "lanyard_form"))')
        self.assertEqual(checks(report)["parts_apart:a:b"]["rests_on"], ["lanyard_form"])

    def test_two_printed_parts_that_overlap_rest_on_nothing_as_before(self) -> None:
        _, _, report, _ = go('show(("a", Box(20, 20, 20)), ("b", Pos(10, 0, 0) * Box(20, 20, 20)))', NUMBERS)
        self.assertEqual(checks(report)["parts_apart:a:b"]["rests_on"], [])

    def test_a_reference_apart_from_the_rest_still_rests_its_check_on_its_form(self) -> None:
        _, _, report, _ = go('show(("strap", Box(20, 20, 20), "reference", "lanyard_form"), ("lid", Pos(100, 0, 0) * Box(20, 20, 20)))')
        found = checks(report)
        apart = [n for n in found if n.startswith("parts_apart")]
        self.assertEqual(len(apart), 1)
        self.assertEqual(found[apart[0]]["actual"], 0)
        self.assertEqual(found[apart[0]]["rests_on"], ["lanyard_form"])


if __name__ == "__main__":
    unittest.main()
