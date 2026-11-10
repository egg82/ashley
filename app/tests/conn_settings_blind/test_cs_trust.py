"""Her tools cannot write the settings, and the household's specifics are not in shipped data. The first is structural:
no module reachable by import from `ashley.tools`, `ashley.channels` or `ashley.inference` holds a write to the settings
tables."""

import ast
import json
import re
from collections.abc import Mapping
from pathlib import Path

import ashley
from source_tree import Parsed

ROOT = Path(ashley.__file__).resolve().parent
HERS = ("tools", "channels", "inference")
WRITE = re.compile(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+connection_settings", re.I)

Files = Mapping[Path, tuple[str, ast.Module]]
"""Each module's path, with its source and its parsed tree."""


def package_files(python_tree: Mapping[Path, Parsed]) -> Files:
    """The modules of `ashley` from the session's parsed tree."""
    return {p: (parsed.source, parsed.tree) for p, parsed in python_tree.items() if ROOT in p.parents}


def read(root: Path) -> Files:
    """Every module under `root`, read and parsed here (for a planted package)."""
    return {p: (source, ast.parse(source)) for p in sorted(root.rglob("*.py")) for source in [p.read_text()]}


def imports_of(path: Path, files: Files, root: Path, package: str) -> set[Path]:
    module = path.relative_to(root).with_suffix("").parts
    here = (package, *module[:-1]) if path.name != "__init__.py" else (package, *module[:-1])
    found: set[Path] = set()
    for node in ast.walk(files[path][1]):
        names: list[tuple[str, ...]] = []
        if isinstance(node, ast.Import):
            names = [tuple(a.name.split(".")) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = tuple((node.module or "").split(".")) if node.module else ()
            if node.level:
                base = here[: len(here) - (node.level - 1)] + base
            names = [base, *(base + (a.name,) for a in node.names)]
        for name in names:
            if name[:1] != (package,):
                continue
            target = root.joinpath(*name[1:])
            for candidate in (target.with_suffix(".py"), target / "__init__.py"):
                if candidate in files:
                    found.add(candidate)
    return found


def closure(files: Files, root: Path, package: str, starts: tuple[str, ...]) -> set[Path]:
    todo = [p for p in files if any((root / s) in p.parents for s in starts)]
    seen: set[Path] = set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        todo.extend(imports_of(path, files, root, package))
    return seen


def writers(reached: set[Path], files: Files) -> list[Path]:
    return sorted(p for p in reached if WRITE.search(files[p][0]))


def test_nothing_her_tools_import_writes_the_settings(python_tree: Mapping[Path, Parsed]) -> None:
    files = package_files(python_tree)
    reached = closure(files, ROOT, "ashley", HERS)
    assert len(reached) > 50 and ROOT / "tools" / "house_act.py" in reached
    assert writers(reached, files) == []


def test_the_scan_finds_a_planted_writer_and_a_real_one_exists(tmp_path: Path, python_tree: Mapping[Path, Parsed]) -> None:
    pkg = tmp_path / "ashley"
    (pkg / "tools").mkdir(parents=True)
    (pkg / "store").mkdir()
    for init in (pkg / "__init__.py", pkg / "tools" / "__init__.py", pkg / "store" / "__init__.py"):
        init.write_text("")
    (pkg / "store" / "put.py").write_text('SQL = "UPDATE connection_settings SET version = 1"\n')
    (pkg / "tools" / "a.py").write_text("from ..store import put\n")
    made = read(pkg)
    planted = closure(made, pkg, "ashley", ("tools",))
    assert writers(planted, made) == [pkg / "store" / "put.py"]
    files = package_files(python_tree)
    everything = set(files)
    assert writers(everything, files), "no module on the tree writes the settings: the scan is blind"
    assert not any(p.relative_to(ROOT).parts[0] in HERS for p in writers(everything, files))


def test_the_shipped_house_data_names_no_household_entity() -> None:
    shipped = ROOT / "tools"
    data = json.loads((shipped / "home_assistant.json").read_text())
    assert set(data) == {"excluded"}
    tiers = json.loads((shipped / "tiers.json").read_text())
    assert not tiers.get("consequential_entities")
    text = (shipped / "home_assistant.json").read_text() + (shipped / "tiers.json").read_text()
    for moore in ("todo.inbox", "todo.groceries", "weekly_shopping", "drive_time", "find_person",
                  "find_recipe", "recipe_details", "weather.get_forecasts"):
        assert moore not in text
