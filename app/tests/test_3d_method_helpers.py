"""The 3D method teaches the CAD helper by name: every name the seed imports from `ashley_cad` is defined there."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "app" / "ashley" / "skills" / "seeds" / "3d.md"
HELPER = ROOT / "deploy" / "cad" / "ashley_cad.py"


def imported_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in re.findall(r"^from ashley_cad import (.+)$", text, re.MULTILINE):
        names |= {n.strip() for n in line.split(",")}
    return names


def defined_names(source: str) -> set[str]:
    return {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def test_every_helper_the_method_imports_exists() -> None:
    wanted = imported_names(SEED.read_text())
    assert {"check", "measured", "show", "existing", "joined", "cut_away"} <= wanted
    assert wanted <= defined_names(HELPER.read_text())


def test_the_name_finder_sees_a_missing_helper() -> None:
    assert imported_names("from ashley_cad import a, ghost") - defined_names("def a(): pass") == {"ghost"}
