"""No two non-test modules that pytest puts on sys.path share a basename. Under the
default `prepend` import mode every directory holding a test file or a conftest is
inserted into sys.path, and `pytest.ini`'s `pythonpath` adds more; one session then
imports `import ha_support` from whichever directory came first, so the other suite
fails at import on CI, or passes locally by ordering luck. Name a helper after its
suite (`<suite>_support.py`)."""

import configparser
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def is_test_file(p: Path) -> bool:
    return p.name == "conftest.py" or p.name.startswith("test_") or p.stem.endswith("_test")


def import_roots(app: Path) -> list[Path]:
    """Directories importable by bare module name in one pytest session."""
    ini = configparser.ConfigParser()
    ini.read(app / "pytest.ini")
    roots = {(app / d).resolve() for d in ini["pytest"]["pythonpath"].split()}
    for p in (app / "tests").rglob("*.py"):
        if is_test_file(p) and "__pycache__" not in p.parts:
            roots.add(p.parent.resolve())
    return sorted(roots)


def collisions(app: Path) -> dict[str, list[Path]]:
    by_name: dict[str, list[Path]] = defaultdict(list)
    for d in import_roots(app):
        for p in d.glob("*.py"):
            if not is_test_file(p) and p.name != "__init__.py":
                by_name[p.stem].append(p)
    return {name: sorted(ps) for name, ps in by_name.items() if len(ps) > 1}


def test_the_gate_sees_the_helpers():
    roots = import_roots(ROOT)
    assert TESTS.resolve() in roots, "pytest.ini's pythonpath no longer includes tests"
    assert len(roots) > 1, "no test directory found: the gate would pass on nothing"
    assert (TESTS / "pg.py").is_file() and "pg" in {
        p.stem for d in roots for p in d.glob("*.py")
    }


def test_no_two_helper_modules_share_a_basename():
    clash = collisions(ROOT)
    assert not clash, "\n".join(
        f"{name}: " + ", ".join(p.relative_to(ROOT).as_posix() for p in ps)
        for name, ps in sorted(clash.items())
    )


def _tree(tmp: Path, helpers: list[str]) -> Path:
    (tmp / "tests" / "suite_a").mkdir(parents=True)
    (tmp / "tests" / "suite_b").mkdir()
    (tmp / "tools").mkdir()
    (tmp / "pytest.ini").write_text("[pytest]\npythonpath = . tools tests\n")
    for rel in helpers:
        (tmp / rel).write_text("")
    for d in ("suite_a", "suite_b"):
        (tmp / "tests" / d / "test_x.py").write_text("")
    return tmp


def test_a_duplicate_helper_is_caught(tmp_path: Path):
    app = _tree(
        tmp_path,
        ["tests/suite_a/ha_support.py", "tests/suite_b/ha_support.py", "tests/suite_a/a_support.py"],
    )
    assert list(collisions(app)) == ["ha_support"]


def test_a_helper_clashing_with_a_top_level_or_tools_module_is_caught(tmp_path: Path):
    app = _tree(tmp_path, ["tests/pg.py", "tests/suite_a/pg.py", "tools/held.py", "tests/suite_b/held.py"])
    assert sorted(collisions(app)) == ["held", "pg"]


def test_distinct_helpers_and_repeated_test_names_pass(tmp_path: Path):
    app = _tree(tmp_path, ["tests/suite_a/a_support.py", "tests/suite_b/b_support.py"])
    (app / "tests" / "suite_a" / "conftest.py").write_text("")
    (app / "tests" / "suite_b" / "conftest.py").write_text("")
    assert collisions(app) == {}
