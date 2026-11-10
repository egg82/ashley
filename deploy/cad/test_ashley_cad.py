"""Tests of ashley_cad, run in the CAD image (it needs build123d, which the CI test image does not hold):

    podman run --rm --read-only --network=none --user 65534 --tmpfs /work:rw,mode=1777 -w /work \
      -v $PWD/test_ashley_cad.py:/test/test_ashley_cad.py:ro -v $PWD/test_ashley_print.py:/test/test_ashley_print.py:ro \
      -v $PWD/../../app/tests/cad_models:/test/models:ro -v $PWD/../../app/ashley/workshop/print.json:/test/print.json:ro \
      localhost/ashley-cad:test python -m unittest discover -v -s /test

Each case runs a script as the sandbox does: a fresh `python -c` in an empty working directory, given the print settings
the app ships (`app/ashley/workshop/print.json`) unless it says otherwise."""

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

MEASUREMENTS = {"items": [
    {"name": "board_width", "value": 60.0, "unit": "mm", "source": "measured"},
    {"name": "hole", "value": 3.2, "unit": "mm", "source": "guessed"}]}

MODEL = """
from build123d import Box, BuildPart, Cylinder, Mode, Locations, Pos
from ashley_cad import check, measured, show
width = measured("board_width")
with BuildPart() as p:
    Box(width + 4, 40, 20)
    with Locations((0, 0, 0)):
        Cylinder(measured("hole") / 2, 30, mode=Mode.SUBTRACT)
bb = p.part.bounding_box()
check("room", bb.size.X - width, ">=", 3.5, tolerance=0.1, rests_on=["board_width"])
check("all_read", bb.size.Y, "==", 40.0)
show(p, ("lid", Pos(60, 0, 0) * Box(10, 10, 2)))
"""


MODELS = Path(__file__).parent / "models"
"""Real model files (`app/tests/cad_models`), as the sandbox is handed a bench's file pieces."""
SHIPPED = json.loads((Path(__file__).parent / "print.json").read_text())


def hand_over(work: Path, models: dict[int, str], left_out: list[dict] | None = None) -> None:
    """What the runner leaves for a run given the model files `models` (piece id -> file name): the files under
    `inputs/` and the index `existing` reads."""
    (work / "inputs").mkdir()
    items = []
    for piece, name in models.items():
        target = work / "inputs" / f"{piece}{Path(name).suffix.lower()}"
        shutil.copy(MODELS / name, target)
        items.append({"piece": piece, "name": Path(name).name, "file": f"inputs/{target.name}", "size": target.stat().st_size})
    (work / "inputs.json").write_text(json.dumps({"items": items, "left_out": left_out or []}))


def run(script: str, measurements: dict | None = MEASUREMENTS, models: dict[int, str] | None = None,
        left_out: list[dict] | None = None, printing: dict | None = SHIPPED) -> tuple[subprocess.CompletedProcess[str], Path]:
    work = Path(tempfile.mkdtemp(dir="/work"))
    if measurements is not None:
        (work / "measurements.json").write_text(json.dumps(measurements))
    if printing is not None:
        (work / "print.json").write_text(json.dumps(printing))
    if models is not None:
        hand_over(work, models, left_out)
    done = subprocess.run([sys.executable, "-B", "-c", script], cwd=work, capture_output=True, text=True)
    return done, work / "out"


def glb_json(path: Path) -> dict:
    data = path.read_bytes()
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


def glb_triangles(doc: dict) -> int:
    return sum(doc["accessors"][p["indices"]]["count"] for m in doc["meshes"] for p in m["primitives"]) // 3


def threemf_triangles(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        return z.read("3D/3dmodel.model").decode().count("<triangle ")


class ModelRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.done, cls.out = run(MODEL)
        assert cls.done.returncode == 0, cls.done.stderr

    def test_the_three_meshes_and_the_report_are_written(self) -> None:
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["model.3mf", "model.glb", "model.stl", "report.json"])

    def test_every_format_holds_the_same_triangles(self) -> None:
        stl = self.out / "model.stl"
        n = struct.unpack("<I", stl.read_bytes()[80:84])[0]
        self.assertEqual(stl.stat().st_size, 84 + 50 * n)
        self.assertGreater(n, 100)
        self.assertEqual(threemf_triangles(self.out / "model.3mf"), n)
        self.assertEqual(glb_triangles(glb_json(self.out / "model.glb")), n)
        self.assertEqual(json.loads((self.out / "report.json").read_text())["triangles"], n)

    def test_glb_is_metres_and_the_report_is_millimetres(self) -> None:
        doc = glb_json(self.out / "model.glb")
        top = max(a["max"][1] for a in doc["accessors"] if a.get("type") == "VEC3" and "max" in a)
        self.assertAlmostEqual(top, 0.02, places=3)   # the 40 mm side lies on Y after the turn to Y-up, as metres
        report = json.loads((self.out / "report.json").read_text())
        body = report["parts"][0]
        self.assertEqual((report["unit"], body["name"]), ("mm", "part1"))
        self.assertAlmostEqual(body["bbox"]["max"][0] - body["bbox"]["min"][0], 64.0, places=3)
        self.assertAlmostEqual(body["volume"], 64 * 40 * 20 - 3.14159265 * 1.6 ** 2 * 20, delta=1.0)
        self.assertEqual(report["parts"][1]["name"], "lid")

    def test_checks_carry_what_they_rest_on(self) -> None:
        checks = {c["name"]: c for c in json.loads((self.out / "report.json").read_text())["checks"]}
        self.assertEqual(checks["room"]["rests_on"], ["board_width"])
        self.assertEqual(checks["all_read"]["rests_on"], ["board_width", "hole"])
        self.assertAlmostEqual(checks["room"]["actual"], 4.0, places=3)
        self.assertEqual((checks["room"]["op"], checks["room"]["tolerance"]), (">=", 0.1))


PAIR = """
from build123d import Box, Pos
from ashley_cad import joined, show
{body}
"""


def shown(body: str) -> dict:
    """The report of a script that builds boxes and shows them."""
    done, out = run(PAIR.format(body=body), measurements=None)
    assert done.returncode == 0, done.stderr
    return json.loads((out / "report.json").read_text())


class PartsApart(unittest.TestCase):
    def test_two_overlapping_parts_give_one_overlap_and_one_failed_check(self) -> None:
        report = shown('show(("a", Box(20, 20, 20)), ("b", Pos(10, 0, 0) * Box(20, 20, 20)))')
        self.assertEqual(len(report["overlaps"]), 1)
        found = report["overlaps"][0]
        self.assertEqual((found["a"], found["b"]), ("a", "b"))
        self.assertAlmostEqual(found["volume_mm3"], 4000.0, delta=1.0)
        self.assertEqual(found["bbox"]["min"], [0.0, -10.0, -10.0])
        self.assertEqual(found["bbox"]["max"], [10.0, 10.0, 10.0])
        self.assertEqual(len(report["checks"]), 1)
        check = report["checks"][0]
        self.assertEqual((check["name"], check["op"], check["target"], check["tolerance"], check["rests_on"]),
                         ("parts_apart:a:b", "==", 0.0, 0.0, []))
        self.assertAlmostEqual(check["actual"], found["volume_mm3"], places=6)
        self.assertEqual(report["overlap_parts_skipped"], 0)

    def test_touching_joined_and_separate_parts_give_none(self) -> None:
        for body in ('show(("a", Box(20, 20, 20)), ("b", Pos(20, 0, 0) * Box(20, 20, 20)))',
                     'show(("a", joined(Box(20, 20, 20), Pos(10, 0, 0) * Box(20, 20, 20))))',
                     'show(("a", Box(20, 20, 20)), ("b", Pos(50, 0, 0) * Box(20, 20, 20)))'):
            report = shown(body)
            self.assertEqual((report["overlaps"], report["checks"]), ([], []), body)

    def test_a_sliver_is_ignored_and_a_thin_real_overlap_is_not(self) -> None:
        sliver = shown('show(("a", Box(20, 20, 20)), ("b", Pos(20 - 1e-5, 0, 0) * Box(20, 20, 20)))')
        self.assertEqual(sliver["overlaps"], [])
        thin = shown('show(("a", Box(20, 20, 20)), ("b", Pos(20 - 0.01, 0, 0) * Box(20, 20, 20)))')
        self.assertEqual(len(thin["overlaps"]), 1)

    def test_a_block_lifted_into_a_holders_pocket_is_caught_and_one_resting_in_it_is_not(self) -> None:
        holder = 'holder = Box(40, 40, 20) - Pos(0, 0, 5) * Box(30, 30, 20)\n'
        into_floor = shown(holder + 'show(("holder", holder), ("block", Pos(0, 0, -4) * Box(20, 20, 10)))')
        self.assertEqual([(o["a"], o["b"]) for o in into_floor["overlaps"]], [("holder", "block")])
        self.assertAlmostEqual(into_floor["overlaps"][0]["volume_mm3"], 1600.0, delta=1.0)
        resting = shown(holder + 'show(("holder", holder), ("block", Pos(0, 0, 0) * Box(20, 20, 10)))')
        self.assertEqual(resting["overlaps"], [])
        inside = shown('show(("body", Box(40, 40, 40)), ("core", Box(10, 10, 10)))')
        self.assertAlmostEqual(inside["overlaps"][0]["volume_mm3"], 1000.0, delta=1.0)

    def test_every_overlapping_pair_is_found_not_only_the_first(self) -> None:
        report = shown('show(("a", Box(20, 20, 20)), ("b", Pos(5, 0, 0) * Box(20, 20, 20)), ("c", Pos(-5, 0, 0) * Box(20, 20, 20)))')
        self.assertEqual([(o["a"], o["b"]) for o in report["overlaps"]], [("a", "b"), ("a", "c"), ("b", "c")])
        self.assertEqual([c["name"] for c in report["checks"]], ["parts_apart:a:b", "parts_apart:a:c", "parts_apart:b:c"])

    def test_the_boolean_runs_only_for_pairs_whose_boxes_meet(self) -> None:
        script = """
import ashley_cad
from build123d import Box, Pos
calls = []
real = ashley_cad._overlap
ashley_cad._overlap = lambda a, b: calls.append(1) or real(a, b)
corner = Box(30, 30, 30) - Pos(10, 10, 0) * Box(20, 20, 40)
ashley_cad.show(("corner", corner), ("far", Pos(100, 0, 0) * Box(5, 5, 5)), ("notch", Pos(10, 10, 0) * Box(10, 10, 10)))
print(len(calls))
"""
        done, out = run(script, measurements=None)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "1")
        self.assertEqual(json.loads((out / "report.json").read_text())["overlaps"], [])

    def test_only_the_first_eight_parts_are_compared_and_the_rest_counted(self) -> None:
        apart = ", ".join(f'("p{i}", Pos({60 * i}, 0, 0) * Box(20, 20, 20))' for i in range(8))
        report = shown(f'show({apart}, ("last", Box(20, 20, 20)))')
        self.assertEqual((report["overlaps"], report["overlap_parts_skipped"]), ([], 1))
        far = ", ".join(f'("p{i}", Pos({60 * i}, 100, 0) * Box(20, 20, 20))' for i in range(1, 7))
        report = shown(f'show(("a", Box(20, 20, 20)), ("b", Pos(5, 0, 0) * Box(20, 20, 20)), {far}, ("late", Pos(-5, 0, 0) * Box(20, 20, 20)))')
        self.assertEqual([(o["a"], o["b"]) for o in report["overlaps"]], [("a", "b")])
        self.assertEqual(report["overlap_parts_skipped"], 1)


class Refusals(unittest.TestCase):
    def fails(self, script: str, text: str, measurements: dict | None = MEASUREMENTS) -> None:
        done, out = run("from ashley_cad import *\n" + script, measurements)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(text, done.stderr)
        self.assertFalse(out.exists())

    def test_an_unknown_measurement_names_the_known_ones(self) -> None:
        self.fails("measured('nope')", "['board_width', 'hole']")

    def test_no_measurements_piece_is_said_plainly(self) -> None:
        self.fails("measured('x')", "no measurements piece", measurements=None)

    def test_a_bad_check_is_refused(self) -> None:
        self.fails("check('a', 1.0, '!=', 2.0)", "op '!='")
        self.fails("check('a', float('nan'), '==', 2.0)", "finite")
        self.fails("check('a', 1.0, '==', 2.0)\ncheck('a', 1.0, '==', 2.0)", "already used")

    def test_a_check_resting_on_an_unmeasured_name_is_refused(self) -> None:
        self.fails("check('a', 1.0, '==', 2.0, rests_on=['ghost'])", "ghost")

    def test_show_with_no_part_is_refused(self) -> None:
        self.fails("show()", "at least one part")


STRAP_ROWS = {"items": [
    {"kind": "choice", "name": "lanyard_form", "label": "The lanyard", "value": "flat woven strap",
     "options": ["flat woven strap", "round cord"], "source": "guessed"},
    {"name": "strap_width", "value": 20.0, "unit": "mm", "source": "guessed", "given": "lanyard_form"},
    {"name": "strap_thickness", "value": 1.5, "unit": "mm", "source": "guessed", "given": "lanyard_form"}]}
"""A lanyard as a bench's first rows would have it: a flat strap, every row guessed."""

STRAP = """
# A lanyard holder in small: a block with a slot sized from the strap's rows, and the strap as a reference
# stand-in resting on the slot's floor, touching and not overlapping. The strap names its form, `lanyard_form`.
from build123d import Box, Pos
from ashley_cad import check, measured, show

width, thick = measured("strap_width"), measured("strap_thickness")
clear, floor = 0.4, 2.0
height = thick + 2 * floor
holder = Box(width + 6, 20, height) - Pos(0, 0, floor) * Box(width + 2 * clear, 22, height)
strap = Pos(0, 0, -height / 2 + floor + thick / 2) * Box(width, 40, thick)
check("strap_shown_wide", strap.bounding_box().size.X, "==", width, tolerance=0.01)
show(("holder", holder, "fit"), ("strap", strap, "reference", "lanyard_form"))
"""


class Forms(unittest.TestCase):
    def fails(self, script: str, text: str, measurements: dict | None = STRAP_ROWS) -> None:
        done, out = run("from build123d import Box, Pos\nfrom ashley_cad import *\n" + script, measurements)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(text, done.stderr)
        self.assertFalse(out.exists())

    def test_a_reference_part_without_a_form_fails_the_run_naming_the_fix(self) -> None:
        self.fails('show(("box", Box(5, 5, 5), "fit"), ("strap", Pos(20, 0, 0) * Box(5, 5, 5), "reference"))',
                   "say what kind of thing it is with a choice row")
        self.fails('show(("strap", Box(5, 5, 5), "reference"))', "the bench has the choices []", measurements=None)

    def test_a_form_that_is_not_a_choice_row_or_on_a_part_that_is_not_a_reference_fails(self) -> None:
        self.fails('show(("strap", Box(5, 5, 5), "reference", "strap_width"))', "is not a choice row")
        self.fails('show(("strap", Box(5, 5, 5), "reference", "ghost"))', "['lanyard_form']")
        self.fails('show(("box", Box(5, 5, 5), "fit", "lanyard_form"))', "only a reference part names a form")

    def test_chosen_reads_a_choice_and_measured_reads_only_numbers(self) -> None:
        done, _ = run("from ashley_cad import chosen\nprint(chosen('lanyard_form'))", STRAP_ROWS)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "flat woven strap"), done.stderr)
        self.fails("measured('lanyard_form')", "read with chosen('lanyard_form')")
        self.fails("chosen('strap_width')", "the bench has the choices ['lanyard_form']")

    def test_a_check_rests_on_the_choice_its_numbers_are_given_and_on_one_read(self) -> None:
        done, out = run("from ashley_cad import *\nfrom build123d import Box\nchosen('lanyard_form')\ncheck('f', 1.0, '>=', 0.0)\n"
                        "measured('strap_thickness')\ncheck('t', 1.0, '>=', 0.0)\nshow(Box(1, 1, 1))", STRAP_ROWS)
        self.assertEqual(done.returncode, 0, done.stderr)
        checks = {c["name"]: c["rests_on"] for c in json.loads((out / "report.json").read_text())["checks"]}
        self.assertEqual(checks, {"f": ["lanyard_form"], "t": ["lanyard_form", "strap_thickness"]})
        done, out = run("from ashley_cad import *\nfrom build123d import Box\nmeasured('strap_width')\ncheck('w', 1.0, '>=', 0.0)\n"
                        "show(Box(1, 1, 1))", STRAP_ROWS)
        self.assertEqual(done.returncode, 0, done.stderr)
        checks = {c["name"]: c["rests_on"] for c in json.loads((out / "report.json").read_text())["checks"]}
        self.assertEqual(checks, {"w": ["strap_width", "lanyard_form"]})

    def test_parts_apart_against_a_reference_part_rests_on_its_form_even_when_apart(self) -> None:
        done, out = run(STRAP, STRAP_ROWS)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads((out / "report.json").read_text())
        self.assertEqual([(p["name"], p["role"], p.get("form")) for p in report["parts"]],
                         [("holder", "fit", None), ("strap", "reference", "lanyard_form")])
        apart = [c for c in report["checks"] if c["name"].startswith("parts_apart")]
        self.assertEqual([(c["name"], c["actual"], c["op"], c["target"], c["rests_on"]) for c in apart],
                         [("parts_apart:holder:strap", 0.0, "==", 0.0, ["lanyard_form"])])
        self.assertEqual(report["overlaps"], [])
        captured = json.loads((MODELS / "strap_reference_report.json").read_text())
        self.assertEqual(([p.get("form") for p in report["parts"]], report["checks"]),
                         ([p.get("form") for p in captured["parts"]], captured["checks"]))


def ascii_stl(name: str) -> Path:
    """The real binary STL `name` written out as ASCII, which is how an ASCII file of a real part looks."""
    data = (MODELS / name).read_bytes()
    n = struct.unpack("<I", data[80:84])[0]
    lines = ["solid part"]
    for i in range(n):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        lines += ["facet normal %.9e %.9e %.9e" % v[:3], "outer loop"] + ["vertex %.9e %.9e %.9e" % v[3 + 3 * k:6 + 3 * k] for k in range(3)] \
            + ["endloop", "endfacet"]
    lines.append("endsolid part")
    target = Path(tempfile.mkdtemp(dir="/work")) / "part.stl"
    target.write_text("\n".join(lines) + "\n")
    return target


FEATURE = {1: "featuretype.STL", 2: "featuretype.3MF", 3: "featuretype.STEP"}
SIZE_MM = (127.0, 63.5, 34.925)
"""The same part in the three files: 5 x 2.5 x 1.375 inches. The STL and the 3MF say nothing of inches in their numbers
(the 3MF declares it), the STEP is in millimetres."""

SIZE = """
from ashley_cad import existing
from build123d import Axis
shape = existing({piece}{unit})
box = shape.bounding_box()
print(type(shape).__name__, len(shape.solids()), shape.volume, box.size.X, box.size.Y, box.size.Z)
"""


def sizes(piece: int, unit: str = "") -> list[float]:
    done, _ = run(SIZE.format(piece=piece, unit=unit), models=FEATURE)
    assert done.returncode == 0, done.stderr
    return [float(v) for v in done.stdout.split()[2:]]


class ExistingModels(unittest.TestCase):
    def test_the_same_part_in_stl_3mf_and_step_comes_back_the_same_size_in_millimetres(self) -> None:
        from_stl, from_3mf, from_step = sizes(1, ', unit="in"'), sizes(2), sizes(3)
        for found in (from_stl, from_3mf, from_step):
            for got, want in zip(found[1:], SIZE_MM):
                self.assertAlmostEqual(got, want, delta=0.05)
        self.assertAlmostEqual(from_stl[0], from_step[0], delta=0.01 * from_step[0])
        self.assertAlmostEqual(from_3mf[0], from_step[0], delta=0.01 * from_step[0])

    def test_an_stl_with_no_unit_given_is_read_as_millimetres(self) -> None:
        self.assertAlmostEqual(sizes(1)[1], 5.0, delta=0.01)

    def test_a_file_that_declares_its_unit_refuses_one_given(self) -> None:
        for piece in (2, 3):
            done, _ = run(SIZE.format(piece=piece, unit=', unit="in"'), models=FEATURE)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("declare their unit", done.stderr)

    def test_a_binary_stl_whose_header_begins_solid_loads(self) -> None:
        done, _ = run(SIZE.format(piece=1, unit=""), models={1: "idler_riser.STL"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreater(float(done.stdout.split()[2]), 0.0)

    def test_the_ascii_form_of_a_part_loads_as_the_same_part(self) -> None:
        text = ascii_stl("featuretype.STL")
        done, _ = run(SIZE.format(piece=1, unit=', unit="in"'), models={1: str(text)})
        self.assertEqual(done.returncode, 0, done.stderr)
        got = [float(v) for v in done.stdout.split()[2:]]
        self.assertAlmostEqual(got[0], sizes(1, ', unit="in"')[0], delta=1.0)
        self.assertAlmostEqual(got[1], SIZE_MM[0], delta=0.05)

    def test_meshes_that_do_not_close_into_a_solid_are_refused_in_words(self) -> None:
        for name in ("teapot.stl", "multibody.stl"):
            done, _ = run(SIZE.format(piece=1, unit=""), models={1: name})
            self.assertNotEqual(done.returncode, 0, name)
            self.assertIn("does not close into a solid", done.stderr)

    def test_a_piece_that_is_not_an_input_names_the_ones_that_are_and_the_ones_left_out(self) -> None:
        done, _ = run(SIZE.format(piece=9, unit=""), models=FEATURE, left_out=[{"piece": 5, "name": "big.stl", "why": "too_large"}])
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("piece 9 is not an input", done.stderr)
        self.assertIn("'featuretype.STL'", done.stderr)
        self.assertIn("big.stl (too_large)", done.stderr)

    def test_a_clip_added_to_an_imported_stl_is_shown_and_reported(self) -> None:
        script = """
from build123d import Box, Pos
from ashley_cad import existing, joined, show
holder = existing(1, unit="in")
top = holder.bounding_box().max.Z
clip = Pos(holder.center().X, holder.center().Y, top) * Box(10, 10, 6)
show(("holder", joined(holder, clip)))
"""
        done, out = run(script, models=FEATURE)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads((out / "report.json").read_text())
        grown = report["parts"][0]["bbox"]["max"][2] - report["parts"][0]["bbox"]["min"][2]
        self.assertAlmostEqual(grown, SIZE_MM[2] + 3.0, delta=0.05)
        self.assertGreater(report["parts"][0]["volume"], sizes(1, ', unit="in"')[0])
        n = struct.unpack("<I", (out / "model.stl").read_bytes()[80:84])[0]
        self.assertEqual((out / "model.stl").stat().st_size, 84 + 50 * n)

    def test_the_glb_of_an_imported_mesh_is_one_indexed_primitive_not_one_per_triangle(self) -> None:
        done, out = run("from ashley_cad import existing, show\nshow(existing(1, unit='in'))", models=FEATURE)
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = glb_json(out / "model.glb")
        n = struct.unpack("<I", (out / "model.stl").read_bytes()[80:84])[0]
        self.assertGreater(n, 3000)
        self.assertEqual(glb_triangles(doc), n)
        self.assertEqual([len(m["primitives"]) for m in doc["meshes"]], [1] * len(doc["meshes"]))
        self.assertLess(len(doc["accessors"]), 10)
        self.assertLess((out / "model.glb").stat().st_size, 100 * n)


class Fake:
    """Shapes as far as `joined` and `cut_away` look: a volume, and what `+` and `-` give."""

    def __init__(self, volume: float, plus: float, minus: float) -> None:
        self.volume, self._plus, self._minus = volume, plus, minus

    def __add__(self, other: "Fake") -> "Fake":
        return Fake(self._plus, 0, 0)

    def __sub__(self, other: "Fake") -> "Fake":
        return Fake(self._minus, 0, 0)


class BooleanGuards(unittest.TestCase):
    def verdict(self, call: str, base: float, part: float, plus: float, minus: float) -> subprocess.CompletedProcess[str]:
        script = f"""
import sys; sys.path.insert(0, {str(Path(__file__).parent)!r})
from test_ashley_cad import Fake
from ashley_cad import joined, cut_away
{call}(Fake({base}, {plus}, {minus}), Fake({part}, 0, 0))
"""
        return subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True)

    def test_a_union_that_kept_only_the_added_part_is_refused(self) -> None:
        self.assertNotEqual(self.verdict("joined", 28192.5, 384.0, 384.0, 0).returncode, 0)

    def test_a_union_holding_the_base_and_no_more_than_both_passes(self) -> None:
        for kept in (28192.5, 28384.5, 28576.5):
            self.assertEqual(self.verdict("joined", 28192.5, 384.0, kept, 0).returncode, 0)
        self.assertNotEqual(self.verdict("joined", 28192.5, 384.0, 28600.0, 0).returncode, 0)

    def test_a_cut_that_removed_everything_or_added_volume_is_refused(self) -> None:
        self.assertNotEqual(self.verdict("cut_away", 28192.5, 384.0, 0, 0.0).returncode, 0)
        self.assertNotEqual(self.verdict("cut_away", 28192.5, 384.0, 0, 28200.0).returncode, 0)

    def test_a_cut_losing_no_more_than_the_part_passes(self) -> None:
        for kept in (28192.5, 28000.5, 27808.5):
            self.assertEqual(self.verdict("cut_away", 28192.5, 384.0, 0, kept).returncode, 0)


if __name__ == "__main__":
    unittest.main()
