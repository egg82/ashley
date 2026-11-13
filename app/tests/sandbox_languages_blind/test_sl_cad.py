"""The part of the `ashley_cad` helper (deploy/cad/ashley_cad.py) a caller can rely on without build123d: the
facts a script reads and the comparisons it may record. `show` meshes with build123d, which the test image does
not hold, so its files and report are checked by the helper's own tests in the CAD image and not here."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

HELPER = Path(__file__).resolve().parents[3] / "deploy" / "cad" / "ashley_cad.py"
DOCUMENTED_OPS = ("==", "<=", ">=", "<", ">")


def fresh(workdir: Path, facts: dict[str, float] | None = None) -> ModuleType:
    """The helper imported anew (it keeps what a script read), with `facts.json` (decisions.md, "Measurements are structured data") in the working directory."""
    if facts is not None:
        items = [{"name": name, "value": value, "unit": "mm", "source": "measured"} for name, value in facts.items()]
        (workdir / "facts.json").write_text(json.dumps({"items": items}))
    spec = importlib.util.spec_from_file_location("ashley_cad_under_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_it_imports_without_build123d(workdir: Path) -> None:
    assert fresh(workdir, {}) is not None


def test_a_measurement_is_read_from_the_working_directory_in_its_unit(workdir: Path) -> None:
    helper = fresh(workdir, {"board_width": 61.5, "holes": 4, "angle": -12.25})
    assert helper.measured("board_width") == 61.5
    assert helper.measured("holes") == 4
    assert helper.measured("angle") == -12.25


def test_each_measurement_is_its_own_value(workdir: Path) -> None:
    helper = fresh(workdir, {"a": 1.0, "b": 2.0})
    assert (helper.measured("b"), helper.measured("a"), helper.measured("b")) == (2.0, 1.0, 2.0)


def test_the_operators_a_check_takes_are_the_documented_five(workdir: Path) -> None:
    assert tuple(fresh(workdir, {}).OPS) == DOCUMENTED_OPS


@pytest.mark.parametrize("op", DOCUMENTED_OPS)
def test_a_check_with_a_documented_operator_is_recorded_without_error(workdir: Path, op: str) -> None:
    helper = fresh(workdir, {"w": 10.0})
    helper.measured("w")
    helper.check("clearance", 2.0, op, 1.5)
    helper.check("clearance_toleranced", 2.0, op, 1.5, tolerance=0.1, rests_on=["w"])


@pytest.mark.parametrize("op", ["!=", "=", "=>", "=<", "", "approx", "in"])
def test_a_check_with_any_other_operator_is_refused(workdir: Path, op: str) -> None:
    helper = fresh(workdir, {})
    with pytest.raises(Exception):
        helper.check("clearance", 2.0, op, 1.5)
