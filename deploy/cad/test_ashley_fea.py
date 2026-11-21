"""Tests of the weak-points study `ashley_cad.show` runs (`ashley_fea`, `ashley_fem`), in the CAD image as test_ashley_cad.py's
are. The solver is held to a closed-form answer: a cantilever's tip deflection (Euler-Bernoulli plus the shear term) and
root bending stress."""

import json
import struct
import unittest

from test_ashley_cad import glb_json, run

L, B, H, FORCE = 100.0, 10.0, 10.0, 50.0
E, NU = 2200.0, 0.35
"""The PLA row of materials.json: Young's modulus in MPa and the assumed Poisson ratio."""

CANTILEVER = """
from build123d import Axis, Box
from ashley_cad import show, study
beam = Box({L}, {B}, {H})
ends = beam.faces().sort_by(Axis.X)
study("beam", "{material}", {{"wall": ends[0]}}, {{"tip": (ends[-1], (0, 0, -{force}))}}{extra})
show(("beam", beam, "structural"))
"""


def report_of(extra: str = "", material: str = "PLA", force: float = FORCE) -> tuple[dict, object]:
    done, out = run(CANTILEVER.format(L=L, B=B, H=H, material=material, force=force, extra=extra))
    assert done.returncode == 0, done.stderr
    return json.loads((out / "report.json").read_text()), out


class Cantilever(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report, cls.out = report_of(", mesh_mm=2.5")
        cls.entry = cls.report["fea"]["studies"][0]

    def test_the_tip_deflection_is_the_beam_formula_within_three_percent(self) -> None:
        inertia = B * H ** 3 / 12
        bending = FORCE * L ** 3 / (3 * E * inertia)
        shear = FORCE * L / (5 / 6 * E / (2 * (1 + NU)) * B * H)
        self.assertLess(abs(self.entry["max_deflection_mm"] / (bending + shear) - 1), 0.03)

    def test_the_root_stress_is_the_beam_formula_within_five_percent(self) -> None:
        root = FORCE * L * (H / 2) / (B * H ** 3 / 12)
        self.assertLess(abs(self.entry["peak_von_mises_mpa"] / root - 1), 0.05)

    def test_the_peak_is_at_the_wall_end_and_on_the_top_surface(self) -> None:
        x, _, z = self.entry["peak"]["point_mm"]
        self.assertLess(x, -L / 2 + 0.1 * L)
        self.assertAlmostEqual(z, H / 2, places=3)
        self.assertEqual(self.entry["peak"]["nearest_named_face"], "wall")

    def test_the_safety_factor_is_the_across_layer_range_over_the_peak(self) -> None:
        sf, peak = self.entry["safety_factor"], self.entry["peak_von_mises_mpa"]
        self.assertAlmostEqual(sf["low"], 33.6 / peak, places=2)
        self.assertAlmostEqual(sf["high"], 37.6 / peak, places=2)
        self.assertEqual(self.entry["basis"]["assumed"], ["poisson_ratio"])
        self.assertIn("across", self.entry["basis"]["note"])

    def test_a_safety_factor_under_the_minimum_is_a_failed_check(self) -> None:
        check = next(c for c in self.report["checks"] if c["name"] == "fea_safety_factor:beam")
        self.assertEqual((check["op"], check["target"], check["rests_on"]), (">=", 2.0, []))
        self.assertAlmostEqual(check["actual"], self.entry["safety_factor"]["low"])

    def test_double_the_force_doubles_the_stress(self) -> None:
        double, _ = report_of(", mesh_mm=2.5", force=2 * FORCE)
        self.assertAlmostEqual(double["fea"]["studies"][0]["peak_von_mises_mpa"] / self.entry["peak_von_mises_mpa"], 2.0, places=3)

    def test_the_stress_view_is_a_glb_with_a_colour_per_vertex(self) -> None:
        self.assertEqual(self.entry["view"], "stress_beam.glb")
        data = (self.out / "stress_beam.glb").read_bytes()
        self.assertEqual(data[:4], b"glTF")
        self.assertEqual(struct.unpack("<I", data[8:12])[0], len(data))
        doc = glb_json(self.out / "stress_beam.glb")
        attributes = doc["meshes"][0]["primitives"][0]["attributes"]
        self.assertEqual(doc["accessors"][attributes["COLOR_0"]]["count"], doc["accessors"][attributes["POSITION"]]["count"])

    def test_the_mesh_and_time_are_reported(self) -> None:
        mesh = self.entry["mesh"]
        self.assertEqual(mesh["size_mm"], 2.5)
        self.assertGreater(mesh["nodes"], 1000)
        self.assertGreater(self.entry["seconds"], 0)


class Skipped(unittest.TestCase):
    def skipped(self, extra: str = "", material: str = "PLA") -> tuple[dict, dict]:
        report, out = report_of(extra, material)
        return report["fea"]["studies"][0], report

    def assert_no_numbers(self, entry: dict, report: dict, reason: str) -> None:
        self.assertEqual(entry["skip_reason"], reason)
        self.assertTrue(entry["detail"])
        self.assertEqual(set(entry), {"part", "material", "skip_reason", "detail"})
        self.assertFalse([c for c in report["checks"] if c["name"].startswith("fea_")])

    def test_a_mesh_over_the_node_limit_is_too_large_and_has_no_stress(self) -> None:
        self.assert_no_numbers(*self.skipped(", max_nodes=500"), "too_large")

    def test_a_material_that_is_not_in_the_file_is_unknown(self) -> None:
        self.assert_no_numbers(*self.skipped(material="Unobtainium"), "unknown_material")

    def test_a_face_of_another_shape_is_not_found(self) -> None:
        script = """
from build123d import Axis, Box
from ashley_cad import show, study
beam, other = Box(100, 10, 10), Box(30, 30, 30)
ends = beam.faces().sort_by(Axis.X)
study("beam", "PLA", {"wall": ends[0]}, {"tip": (other.faces()[0], (0, 0, -5))})
show(("beam", beam, "structural"))
"""
        done, out = run(script)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads((out / "report.json").read_text())
        self.assert_no_numbers(report["fea"]["studies"][0], report, "face_not_found")

    def test_a_study_without_a_fixed_face_is_refused_before_anything_is_solved(self) -> None:
        done, _ = run("from build123d import Box\nfrom ashley_cad import study\nstudy('b', 'PLA', {}, {'t': (Box(1, 1, 1).faces()[0], (0, 0, 1))})")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("at least one fixed face", done.stderr)

    def test_a_script_with_no_study_has_no_fea_section(self) -> None:
        done, out = run("from build123d import Box\nfrom ashley_cad import show\nshow(Box(5, 5, 5))")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("fea", json.loads((out / "report.json").read_text()))


if __name__ == "__main__":
    unittest.main()
