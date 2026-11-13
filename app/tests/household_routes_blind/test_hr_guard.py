"""Pins the guard on the model-choice writer (`route_choice_write`), mirroring `tests/test_settings_boundary.py`: only
the Usage room's route and the wiring (and the Postgres writer for its own interface) import `RouteChoiceWriter`, so
nothing she does on her own, whether a tool, a channel, the router or a skill, can choose a household's model; the reads
may be imported anywhere."""

import ast
from pathlib import Path

from source_tree import Parsed
from test_boundaries import PKG, dotted, package

WRITERS = {"ashley.inference.route_choice_write", "ashley.inference.postgres_route_choice_write"}
MAY_IMPORT = {"ashley.api.spend_routes", "ashley.wiring_inference", "ashley.inference.postgres_route_choice_write"}
HER_OWN = ("tools", "channels", "skills", "persona", "memory", "senses", "initiative", "errands", "watches", "runs",
           "conversations", "inference.router", "inference.layered_routes")


def importing(modules: dict[str, ast.Module]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for module, tree in modules.items():
        parts = module.split(".")
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                base = parts[: len(parts) - node.level] if node.level else []
                target = ".".join(base + (node.module.split(".") if node.module else []))
                names |= {target, *(f"{target}.{a.name}" for a in node.names)}
        if names & WRITERS:
            found[module] = names & WRITERS
    return found


def test_only_the_route_the_wiring_and_the_postgres_writer_import_the_writer(package_tree: dict[Path, Parsed]) -> None:
    found = importing({dotted(p): f.tree for p, f in package(package_tree).items()})
    assert found, "the gate saw no importer of the writer: it would pass on nothing"
    assert set(found) == MAY_IMPORT, f"importers of the choice writer: {sorted(found)}, allowed {sorted(MAY_IMPORT)}"


def test_nothing_she_does_on_her_own_imports_the_writer(package_tree: dict[Path, Parsed]) -> None:
    modules = {dotted(p): f.tree for p, f in package(package_tree).items()}
    assert any(m.startswith("ashley.tools.") for m in modules), "the tree read held no tools"
    hers = {m for m in importing(modules) if any(m.startswith(f"ashley.{h}") for h in HER_OWN)}
    assert not hers, sorted(hers)


def test_the_writer_modules_exist_where_the_guard_names_them() -> None:
    for name in WRITERS:
        assert (PKG.parent / (name.replace(".", "/") + ".py")).is_file(), name


def test_the_guard_catches_each_way_of_importing_a_writer_and_leaves_the_reads_alone() -> None:
    planted = {
        "ashley.tools.a": "from ..inference.route_choice_write import RouteChoiceWriter\n",
        "ashley.channels.b": "from ..inference import postgres_route_choice_write\n",
        "ashley.inference.c": "from .route_choice_write import RouteChoiceWriter\n",
        "ashley.tools.deep.d": "import ashley.inference.postgres_route_choice_write\n",
        "ashley.tools.clean": "from ..inference.route_choices import RouteChoiceReads, Choice\n",
        "ashley.tools.household": "from ..inference.household_routes import HouseholdRoutes\n"}
    found = importing({m: ast.parse(src) for m, src in planted.items()})
    assert set(found) == {"ashley.tools.a", "ashley.channels.b", "ashley.inference.c", "ashley.tools.deep.d"}
