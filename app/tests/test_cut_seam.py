"""Only the eval entry point may set a prompt cut: nothing in `ashley` outside `ashley.evals` imports `cut.install`, so
production turns never leave out a part of the prompt or a tool."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "ashley"
OWNER = PKG / "channels" / "cut.py"


def setters(source: str) -> list[int]:
    """Lines of `source` that import `install` from the cut module or name `cut.install`."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.module.split(".")[-1] == "cut":
            found += [node.lineno for a in node.names if a.name == "install"]
        elif isinstance(node, ast.Attribute) and node.attr == "install" and isinstance(node.value, ast.Name) \
                and node.value.id == "cut":
            found.append(node.lineno)
    return found


def outside_evals() -> list[Path]:
    return [p for p in PKG.rglob("*.py") if "evals" not in p.relative_to(PKG).parts and p != OWNER]


def test_no_module_outside_the_evals_sets_a_cut() -> None:
    files = outside_evals()
    assert len(files) > 100
    assert {p.name for p in files} >= {"turn_prompt.py", "tool_loop.py"}
    found = {p.relative_to(PKG).as_posix(): setters(p.read_text()) for p in files}
    assert {name: lines for name, lines in found.items() if lines} == {}


def test_the_gate_sees_each_way_to_reach_the_setter() -> None:
    assert setters("from ashley.channels.cut import install\n") == [1]
    assert setters("from . import cut\ncut.install(x)\n") == [2]
    assert setters("from .cut import Cut, install as put\n") == [1]
    assert setters("from . import cut\ncut.active()\n") == []
    assert setters("from ..evals import variant\nvariant.install(None)\n") == []
