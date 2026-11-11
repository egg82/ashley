"""Which top-level modules of the package may import which. Every import counts,
including a lazy one inside a function, since a lazy import still couples the two. A
new edge fails until it is added to ALLOWED, and that is the moment to ask whether
the code belongs where it is. An entry nothing uses fails too, so the list stays what
the code is. `python tests/test_boundaries.py --write` prints today's edges as an
ALLOWED literal to seed it once.

Template from the agentic-engineering skill: set PKG, seed ALLOWED, then shrink it on
purpose."""

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

from source_tree import BRIDGE, KEEPER, Parsed, parse_tree, rel

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "ashley"  # the package directory (its name is the import root)

# Top-level module or subpackage -> those it may import. Seed with --write, then
# cut edges deliberately.
ALLOWED: dict[str, set[str]] = {
    "api": {"channels", "connections", "conversations", "db", "files", "inference", "live", "logs", "looks", "mail", "memory", "people",
            "persona", "runs", "senses", "services", "settings", "signin", "skills", "text", "workshop"},
    "channels": {"stamp", "codehost", "connections", "conversations", "db", "errands", "inference", "initiative", "live", "logs", "memory",
                 "people", "persona", "runs", "senses", "services", "settings", "skills", "text", "tidy", "tools", "watches",
                 "workshop"},
    "codehost": {"connections", "logs", "services"},
    "connections": {"db", "logs", "services"},
    "conversations": {"db", "hearing", "logs", "receipts", "services"},
    "inference": {"connections", "db", "logs", "services", "text"},
    "errands": {"db", "hearing", "services"},
    "files": {"db", "logs", "services"},
    "live": {"db", "logs", "services"},
    "db": {"logs", "services", "settings"},
    "hearing": set[str](),
    "initiative": {"inference", "services"},
    "home_assistant": {"connections", "logs", "services"},
    "google": {"connections", "services"},
    "mail": {"connections", "db", "logs", "runs", "services"},
    "herdr": {"connections", "logs", "services"},
    "receipts": set[str](),
    "stamp": set[str](),
    "text": set[str](),
    "evals": {"channels", "connections", "criteria", "db", "herdr", "home_assistant", "inference", "logs", "memory",
              "people", "persona", "services", "settings", "tools", "watches", "wiring"},
    "memory": {"conversations", "db", "hearing", "inference", "logs", "people", "services", "text"},
    "main": {"api", "db", "logs", "services", "settings", "web", "wiring", "wiring_singletons"},
    "people": {"db", "logs", "services", "settings"},
    "printables": {"logs", "services"},
    "persona": {"conversations", "inference", "memory", "people", "stamp"},
    "referee": {"logs", "services", "settings"},
    "criteria": set[str](),
    "watches": {"connections", "criteria", "db", "errands", "herdr", "logs", "mail", "services"},
    "ledger": {"services"},
    "senses": {"criteria", "db", "home_assistant", "ledger", "logs", "people", "services"},
    "services": {"logs"},
    "signin": {"db", "logs", "people", "services", "settings"},
    "skills": {"db", "logs", "services", "text"},
    "runs": {"db", "files", "logs", "services", "text"},
    "looks": {"db", "logs", "runs", "services"},
    "sure": {"connections", "ledger", "logs", "services"},
    "tools": {"stamp", "codehost", "connections", "criteria", "errands", "files", "herdr", "home_assistant", "inference", "ledger", "live", "logs", "looks", "mail", "people", "printables", "receipts", "runs", "senses", "services",
              "skills", "tidy", "watches", "workshop"},
    "wiring_providers": {"inference", "settings"},
    "wiring_bridge": {"connections", "db", "mail", "runs", "services", "settings"},
    "wiring_sandbox": {"logs", "looks", "runs", "services", "settings"},
    "wiring_skills": {"db", "persona", "services", "skills"},
    "wiring_inference": {"connections", "db", "inference", "services", "settings", "wiring_providers"},
    "wiring_singletons": {"channels", "conversations", "db", "files", "home_assistant", "inference", "logs", "looks", "mail", "memory",
                          "referee", "senses", "services", "settings", "watches", "workshop"},
    "wiring": {"channels", "codehost", "connections", "conversations", "db", "errands", "files", "google", "herdr", "home_assistant", "inference", "initiative", "live",
               "looks", "mail", "memory", "people", "printables", "runs", "senses", "services", "settings", "signin", "sure",
               "tidy", "tools", "watches", "wiring_bridge", "wiring_inference", "wiring_providers", "wiring_sandbox", "wiring_singletons", "wiring_skills",
               "workshop"},
    "tidy": {"db", "inference", "logs", "services", "workshop"},
    "workshop": {"db", "files", "home_assistant", "live", "logs", "runs", "services", "text"},
}

# Third-party libraries fenced behind one adapter -> the modules that may import them, exactly. A library here is
# reached only through its adapter's own interface, so swapping it touches one file.
LIBRARIES: dict[str, set[str]] = {
    "hikari": {"ashley.channels.discord.client"},
    "joserfc": {"ashley.signin.provider"},
    "py_vapid": {"ashley.channels.push.sender"},
    "pywebpush": {"ashley.channels.push.sender"},
    "requests": {"ashley.channels.push.sender"},
    "sherpa_onnx": {"ashley.inference.sherpa_voiceprint"},
}

# Each import cycle ALLOWED contains, as the set of its modules. Only shrinks; adding
# the edge that closes a new cycle fails even after ALLOWED takes it.
CYCLES: list[set[str]] = []


def top(path: Path) -> str:
    rel = path.relative_to(PKG)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def units() -> set[str]:
    """The top-level modules and subpackages; `from pkg import __version__` names
    neither, so names that are not units are not edges."""
    return {top(p) for p in PKG.rglob("*.py")} - {"__init__"}


def edges_of(tree: ast.Module, module: str, is_package: bool = False) -> set[str]:
    """The top-level siblings one module imports, given its dotted name
    (`pkg.sources.alpha`, or `pkg.sources` for a package's `__init__`): `import
    pkg.x`, `from pkg.x import y`, `from pkg import x`, and relative imports resolved
    against the module's own package, at any depth in the file."""
    parts = module.split(".")
    name, own = parts[0], parts[1] if len(parts) > 1 else ""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {
                a.name.split(".")[1] for a in n.names if a.name.startswith(name + ".")
            }
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                # `.` is the module's own package: its parent for a module, itself for a
                # package __init__
                base = parts[: len(parts) - n.level + (1 if is_package else 0)]
                target = base + (n.module.split(".") if n.module else [])
            else:
                target = n.module.split(".") if n.module else []
            if not target or target[0] != name:
                continue
            out |= {target[1]} if len(target) > 1 else {a.name for a in n.names}
    return out - {own, "__init__"}


def libraries_of(tree: ast.Module) -> set[str]:
    """The top-level absolute imports of one parsed module, at any depth in the file."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            out.add(n.module.split(".")[0])
    return out


def package(parsed: dict[Path, Parsed]) -> dict[Path, Parsed]:
    return {p: file for p, file in parsed.items() if PKG in p.parents}


def importers(libraries: Iterable[str], parsed: dict[Path, Parsed]) -> dict[str, set[str]]:
    """The modules importing each of `libraries`. Each file is walked once, not once per library."""
    used = {dotted(p): libraries_of(file.tree) for p, file in package(parsed).items()}
    return {library: {module for module, found in used.items() if library in found} for library in libraries}


def dotted(path: Path) -> str:
    rel = path.relative_to(PKG.parent).with_suffix("")
    return ".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)


def edges(parsed: dict[Path, Parsed]) -> dict[str, set[str]]:
    known = units()
    out: dict[str, set[str]] = {}
    for p, file in package(parsed).items():
        if p.name == "__init__.py" and p.parent == PKG:
            continue
        found = edges_of(file.tree, dotted(p), p.name == "__init__.py")
        out.setdefault(top(p), set()).update(found & known)
    return {k: v for k, v in out.items() if v}


def cycles(graph: dict[str, set[str]]) -> list[set[str]]:
    """Every strongly connected component of more than one module (Tarjan), plus
    self-loops."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    out: list[set[str]] = []

    def visit(v: str) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        for w in graph.get(v, set()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp: set[str] = set()
            while True:
                w = stack.pop()
                comp.add(w)
                if w == v:
                    break
            if len(comp) > 1 or v in graph.get(v, set()):
                out.append(comp)

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return sorted(out, key=sorted)


def test_the_gate_sees_the_package(python_tree: dict[Path, Parsed]):
    assert len(units()) > 1 and edges(python_tree), (
        f"no import edges under {PKG}: gate sees nothing"
    )


def test_the_held_cycles_are_what_allowed_is():
    found = cycles(ALLOWED)
    assert found == sorted(CYCLES, key=sorted), (
        f"import cycles in ALLOWED: {found}, held {CYCLES}; break the new one"
    )


def test_every_import_edge_is_allowed(python_tree: dict[Path, Parsed]):
    new = sorted(
        f"{a} -> {b}" for a, bs in edges(python_tree).items() for b in bs - ALLOWED.get(a, set())
    )
    assert not new, (
        "imports not in ALLOWED "
        "(decide whether the code belongs here, then add the edge):\n" + "\n".join(new)
    )


def test_every_allowed_edge_is_used(python_tree: dict[Path, Parsed]):
    found = edges(python_tree)
    stale = sorted(
        f"{a} -> {b}" for a, bs in ALLOWED.items() for b in bs - found.get(a, set())
    )
    assert not stale, "ALLOWED edges nothing uses (remove them):\n" + "\n".join(stale)


def test_each_fenced_library_is_imported_only_by_its_adapter(python_tree: dict[Path, Parsed]):
    found = importers(LIBRARIES, python_tree)
    assert all(found.values()), f"a fenced library nothing imports (remove it): {found}"
    assert found == LIBRARIES, f"fenced libraries imported outside their adapter: {found}"


def test_the_bridge_imports_nothing_from_ashley(python_tree: dict[Path, Parsed]):
    """`bridge/herdr` runs on a person's machine without the app, so no module there may import `ashley`."""
    bridge = {p: file for p, file in python_tree.items() if BRIDGE in p.parents}
    assert len(bridge) > 5, "the gate sees none of the bridge: it would pass on nothing"
    bad = sorted(rel(p) for p, file in bridge.items() if PKG.name in libraries_of(file.tree))
    assert not bad, "bridge modules importing the app:\n" + "\n".join(bad)


def test_the_keeper_imports_nothing_from_ashley(python_tree: dict[Path, Parsed]):
    """`deploy/mail-bridge` runs in Bridge's pod without the app, so no module there may import `ashley`."""
    keeper = {p: file for p, file in python_tree.items() if KEEPER in p.parents}
    assert len(keeper) > 5, "the gate sees none of the keeper: it would pass on nothing"
    bad = sorted(rel(p) for p, file in keeper.items() if PKG.name in libraries_of(file.tree))
    assert not bad, "keeper modules importing the app:\n" + "\n".join(bad)


def source_edges(source: str, module: str, is_package: bool = False) -> set[str]:
    return edges_of(ast.parse(source), module, is_package)


def source_libraries(source: str) -> set[str]:
    return libraries_of(ast.parse(source))


def test_this_test_can_fail():
    assert source_edges("from pkg.db import x\n", "pkg.api") == {"db"}
    assert source_edges("def f():\n    import pkg.views.page\n", "pkg.api") == {"views"}
    assert source_edges("from . import db, logs\n", "pkg.api") == {"db", "logs"}
    assert source_edges("from .db import conn\nimport os\n", "pkg.api") == {"db"}
    assert source_edges("from pkg import api\n", "pkg.api") == set()
    # inside a subpackage, `from . import base` is a sibling in the same top-level unit,
    # not a new edge
    assert source_edges("from . import base\n", "pkg.sources.alpha") == set()
    assert source_edges("from ..db import conn\n", "pkg.sources.alpha") == {"db"}
    assert (
        source_edges("from .base import x\n", "pkg.sources", is_package=True) == set()
    )  # a package __init__
    assert source_edges("from ..db import x\n", "pkg.sources", is_package=True) == {"db"}
    # libraries: absolute imports at any depth, relative ones never
    assert source_libraries("import hikari.api\ndef f():\n    from hikari import x\n") == {"hikari"}
    assert source_libraries("from .hikari import x\nfrom . import hikari\n") == set()
    assert "ashley" in source_libraries("def f():\n    from ashley.db import conn\n")
    # cycles: none in a chain; a two-cycle and a self-loop are found
    assert cycles({"a": {"b"}, "b": {"c"}}) == []
    assert cycles({"a": {"b"}, "b": {"a"}, "c": {"c"}}) == [{"a", "b"}, {"c"}]


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        found = edges(parse_tree())
        print("ALLOWED = {")
        for k, v in sorted(found.items()):
            print(f"    {k!r}: {sorted(v)!r},".replace("[", "{").replace("]", "}"))
        print("}")
        held = ", ".join(
            "{" + ", ".join(repr(m) for m in sorted(c)) + "}" for c in cycles(found)
        )
        print(f"CYCLES = [{held}]")
