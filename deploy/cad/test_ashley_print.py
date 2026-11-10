"""Tests of the print check `ashley_cad.show` runs (`ashley_print`), in the CAD image as test_ashley_cad.py's are."""

import json
import unittest

from test_ashley_cad import SHIPPED, run

GATE_BLOCK = """
# A gate block from a model run, with the measurements that run had: a 15 mm
# tongue rooted on one side over a 1.2 mm deep mouth, its tip 0.4 mm over a ledge. It printed as its own part there too.
from build123d import Box, Pos
from ashley_cad import show

chan_w, chan_d, span_x, blk_w = 19.8, 4.0, 29.89, 23.8
clearance, stop_gap, tongue_t, tongue_len, stop_overlap = 0.6, 0.4, 0.8, 15.0, 0.8
x0 = -10.24
xc = x0 + span_x / 2
floor_z = -chan_d
wall = 2.0
bottom = floor_z - wall
y_root = -chan_w / 2 + 0.9
y_tip = y_root + tongue_len
y_jaw = y_tip + clearance
blk_top = 0.05
blk = Pos(xc, 0, (bottom + blk_top) / 2) * Box(span_x, blk_w, blk_top - bottom)
blk -= Pos(xc, 0, floor_z / 2) * Box(span_x + 1, chan_w, chan_d)
blk -= Pos(xc, (y_root + y_jaw) / 2, (floor_z + bottom) / 2) * Box(span_x + 1, y_jaw - y_root, wall + 0.02)
tongue = Pos(xc, (y_root + y_tip) / 2, floor_z - tongue_t / 2) * Box(span_x, tongue_len + 0.02, tongue_t)
ledge_top = floor_z - tongue_t - stop_gap
ledge = Pos(xc, (y_tip - stop_overlap + y_jaw) / 2, (ledge_top + bottom) / 2) * Box(span_x, y_jaw - (y_tip - stop_overlap) + 0.02, ledge_top - bottom)
gate = blk + tongue + ledge
show(("gate_test_block", gate, "flexure"){extra})
"""

SHELF = """
# A wall with a shelf 8 mm over the bed: it needs support, and the support comes out.
from build123d import Box, Pos
from ashley_cad import show
part = Box(20, 4, 20) + Pos(0, 7, 0) * Box(20, 10, 4)
show(("shelf", Pos(0, 0, 10) * part, "structural"){extra})
"""

PLAIN = """
from build123d import Box, Pos
from ashley_cad import show
show(("block", Box(30, 20, 10), "enclosure"){extra})
"""


CORD = {"items": [{"kind": "choice", "name": "cord_form", "label": "The cord", "value": "flat strap", "source": "guessed"}]}
"""The form a reference stand-in names."""


def report_of(script: str, extra: str = "", printing: dict | None = SHIPPED, measurements: dict | None = None) -> dict:
    done, out = run(script.format(extra=extra), measurements=measurements, printing=printing)
    assert done.returncode == 0, done.stderr
    return json.loads((out / "report.json").read_text())


def checks(report: dict) -> dict:
    return {c["name"]: c for c in report["checks"]}


class Bench23(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = report_of(GATE_BLOCK)

    def test_the_tongue_tip_over_the_ledge_fails_the_open_gap(self) -> None:
        gap = checks(self.report)["print_gap:gate_test_block"]
        self.assertAlmostEqual(gap["actual"], 0.4, places=3)
        self.assertEqual((gap["op"], gap["target"], gap["tolerance"], gap["rests_on"]), (">=", 0.6, 0.0, []))

    def test_the_support_under_the_tongue_is_trapped(self) -> None:
        trapped = checks(self.report)["print_trapped_support:gate_test_block"]
        self.assertAlmostEqual(trapped["actual"], 1.2, places=3)
        self.assertEqual((trapped["op"], trapped["target"]), (">=", 1.5))

    def test_the_print_section_holds_the_tongue_and_the_skin_over_the_channel_as_islands(self) -> None:
        printing = self.report["print"]
        self.assertEqual(printing["bed_fit_skipped"], "no_bed")
        (entry,) = printing["parts"]
        self.assertEqual(entry["bed_z"], -6.0)
        self.assertEqual((entry["name"], entry["fits_bed"], entry["islands_total"]), ("gate_test_block", None, 2))
        tongue, skin = entry["islands"]
        self.assertEqual((tongue["min_gap_mm"], tongue["median_gap_mm"]), (0.4, 1.2))
        self.assertAlmostEqual(tongue["area_mm2"], 29.89 * 15.01, delta=0.05)
        self.assertEqual((tongue["bbox"]["min"], tongue["bbox"]["max"]), ([-10.24, -9.0, -4.8], [19.65, 6.01, -4.8]))
        # the block's 0.05 mm top over the channel (it fused into the sleeve in the real holder) is 4 mm over its floor
        self.assertEqual((skin["min_gap_mm"], skin["median_gap_mm"]), (4.0, 4.0))
        self.assertAlmostEqual(skin["area_mm2"], 29.89 * 19.8, delta=0.05)
        self.assertAlmostEqual(entry["support_area_mm2"], tongue["area_mm2"] + skin["area_mm2"], places=2)
        self.assertGreater(entry["bed_contact_mm2"], 0)

    def test_the_part_carries_its_role(self) -> None:
        self.assertEqual(self.report["parts"][0]["role"], "flexure")


class Control(unittest.TestCase):
    def test_a_shelf_with_room_under_it_needs_support_and_fails_nothing(self) -> None:
        report = report_of(SHELF)
        self.assertEqual(report["checks"], [])
        (entry,) = report["print"]["parts"]
        self.assertAlmostEqual(entry["support_area_mm2"], 200.0, delta=0.01)
        self.assertEqual([(i["min_gap_mm"], i["median_gap_mm"]) for i in entry["islands"]], [(8.0, 8.0)])
        self.assertAlmostEqual(entry["bed_contact_mm2"], 80.0, delta=0.01)

    def test_a_plain_block_has_no_overhang_and_its_whole_floor_on_the_bed(self) -> None:
        report = report_of(PLAIN)
        (entry,) = report["print"]["parts"]
        self.assertEqual((entry["support_area_mm2"], entry["islands"], entry["islands_total"]), (0.0, [], 0))
        self.assertAlmostEqual(entry["bed_contact_mm2"], 600.0, delta=0.01)
        self.assertEqual(report["checks"], [])


SLOPE = """
from build123d import Polyline, Rot, extrude, make_face
from ashley_cad import show
import math
# A wall on the bed with a ledge leaning out of it at {deg} degrees from vertical, its underside starting 5 mm up: the
# profile is drawn in XY and turned so its Y is up.
run = 6 * math.tan(math.radians({deg}))
profile = Polyline((0, 0), (4, 0), (4, 5), (4 + run, 11), (0, 11), close=True)
part = Rot(90, 0, 0) * extrude(make_face(profile), 10)
show(("lean", part, "decorative"))
"""


class Overhangs(unittest.TestCase):
    def support(self, deg: float) -> float:
        report = report_of(SLOPE.replace("{deg}", str(deg)))
        return report["print"]["parts"][0]["support_area_mm2"]

    def test_a_face_steeper_than_the_threshold_from_vertical_is_an_overhang_and_a_shallower_one_is_not(self) -> None:
        self.assertEqual(self.support(30), 0.0)
        self.assertGreater(self.support(60), 0.0)

    def test_the_threshold_comes_from_the_settings(self) -> None:
        report = report_of(SLOPE.replace("{deg}", "30"), printing={**SHIPPED, "overhang_deg": 20})
        self.assertGreater(report["print"]["parts"][0]["support_area_mm2"], 0.0)

    def test_a_face_pointing_up_is_never_an_overhang(self) -> None:
        upside = report_of(PLAIN.replace('Box(30, 20, 10)', 'Box(30, 20, 10) - Pos(0, 0, 4) * Box(20, 10, 4)'))
        self.assertEqual(upside["print"]["parts"][0]["support_area_mm2"], 0.0)


class Assembled(unittest.TestCase):
    def test_a_lid_shown_on_its_box_is_checked_on_its_own_bed_and_fails_nothing(self) -> None:
        report = report_of(PLAIN, extra=', ("lid", Pos(0, 0, 6) * Box(30, 20, 2), "enclosure")')
        self.assertEqual(report["checks"], [])
        box, lid = report["print"]["parts"]
        self.assertEqual((box["bed_z"], lid["bed_z"]), (-5.0, 5.0))
        self.assertEqual((lid["support_area_mm2"], lid["islands"]), (0.0, []))
        self.assertAlmostEqual(lid["bed_contact_mm2"], 600.0, delta=0.01)

    def test_a_part_shown_in_the_air_sits_on_its_own_bed_with_no_overhang(self) -> None:
        report = report_of(PLAIN, extra=', ("pin", Pos(50, 0, 20) * Box(10, 10, 4), "fit")')
        pin = report["print"]["parts"][1]
        self.assertEqual((pin["bed_z"], pin["support_area_mm2"], pin["islands_total"]), (18.0, 0.0, 0))
        self.assertAlmostEqual(pin["bed_contact_mm2"], 100.0, delta=0.01)
        self.assertEqual(report["checks"], [])


class Reference(unittest.TestCase):
    def test_a_reference_part_under_the_tongue_neither_prints_nor_closes_the_gap(self) -> None:
        cord = ', ("cord", Pos(4.7, -2, -5.5) * Box(20, 6, 0.9), "reference", "cord_form")'
        report = report_of(GATE_BLOCK, extra=cord, measurements=CORD)
        self.assertEqual([p["name"] for p in report["print"]["parts"]], ["gate_test_block"])
        island = report["print"]["parts"][0]["islands"][0]
        self.assertEqual((island["min_gap_mm"], island["median_gap_mm"]), (0.4, 1.2))
        self.assertEqual(report["print"]["parts"][0]["bed_z"], -6.0)
        self.assertEqual([p["role"] for p in report["parts"]], ["flexure", "reference"])

    def test_a_reference_part_is_still_checked_for_overlaps(self) -> None:
        report = report_of(PLAIN, extra=', ("token", Pos(10, 0, 0) * Box(10, 10, 10), "reference", "cord_form")',
                           measurements=CORD)
        self.assertEqual([(c["name"], c["rests_on"]) for c in report["checks"]], [("parts_apart:block:token", ["cord_form"])])
        self.assertGreater(report["checks"][0]["actual"], 0)

    def test_only_reference_parts_skip_the_print_check_with_that_reason(self) -> None:
        report = report_of('from build123d import Box\nfrom ashley_cad import show\nshow(("cord", Box(5, 5, 5), "reference", "cord_form"))',
                           measurements=CORD)
        self.assertEqual(report["print"], {"skipped": "no_printed_parts"})


class Settings(unittest.TestCase):
    def test_no_settings_skip_the_print_check_rather_than_pass_it(self) -> None:
        self.assertEqual(report_of(GATE_BLOCK, printing=None)["print"], {"skipped": "no_settings"})

    def test_a_model_over_the_triangle_cap_is_skipped_with_its_count(self) -> None:
        report = report_of(GATE_BLOCK, printing={**SHIPPED, "max_print_triangles": 10})
        self.assertEqual(report["print"]["skipped"], "too_many_triangles")
        self.assertEqual(report["print"]["max_triangles"], 10)
        self.assertEqual(report["print"]["triangles"], report["triangles"])
        self.assertFalse([c for c in report["checks"] if c["name"].startswith("print_")])

    def test_bed_fit_is_judged_when_the_settings_give_a_bed(self) -> None:
        roomy = report_of(PLAIN, printing={**SHIPPED, "bed_mm": [256, 256, 256]})
        self.assertEqual((roomy["print"]["bed_fit_skipped"], roomy["print"]["parts"][0]["fits_bed"]), (None, True))
        turned = report_of(PLAIN, printing={**SHIPPED, "bed_mm": [25, 35, 20]})
        self.assertTrue(turned["print"]["parts"][0]["fits_bed"])
        small = report_of(PLAIN, printing={**SHIPPED, "bed_mm": [25, 25, 256]})
        self.assertFalse(small["print"]["parts"][0]["fits_bed"])

    def test_bad_settings_fail_the_run_naming_the_key(self) -> None:
        done, _ = run(PLAIN.format(extra=""), measurements=None, printing={**SHIPPED, "min_open_gap_mm": "wide"})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("min_open_gap_mm", done.stderr)


class Roles(unittest.TestCase):
    def test_a_role_off_the_list_is_refused_naming_the_list(self) -> None:
        done, out = run('from build123d import Box\nfrom ashley_cad import show\nshow(("a", Box(5, 5, 5), "holder"))',
                        measurements=None)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("'holder'", done.stderr)
        self.assertIn("'flexure'", done.stderr)
        self.assertFalse(out.exists())

    def test_a_part_without_a_role_is_unknown_and_still_printed(self) -> None:
        report = report_of('from build123d import Box\nfrom ashley_cad import show\nshow(("a", Box(5, 5, 5)), Box(1, 1, 1))')
        self.assertEqual([(p["name"], p["role"]) for p in report["parts"]], [("a", "unknown"), ("part2", "unknown")])
        self.assertEqual([p["name"] for p in report["print"]["parts"]], ["a", "part2"])

    def test_a_tuple_of_another_length_is_refused(self) -> None:
        done, _ = run('from build123d import Box\nfrom ashley_cad import show\nshow(("a", Box(5, 5, 5), "test", 1, 2))',
                      measurements=None)
        self.assertIn("(name, shape, role)", done.stderr)


if __name__ == "__main__":
    unittest.main()
