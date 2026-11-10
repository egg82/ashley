"""Nothing she does on her own can widen what she trusts: the modules that write a connection's settings
(`ashley.connections.settings_write` and the Postgres writer) are imported only by the member route and the wiring that
registers them, so no tool, channel or model call can reach `SettingsWriter` (`decisions.md`, "A connection has settings
its person sets"). An import of either by any other module fails here, whatever package it is in."""

import ast
from pathlib import Path

from source_tree import Parsed
from test_boundaries import PKG, dotted, package

WRITERS = {"ashley.connections.settings_write", "ashley.connections.settings_write_postgres"}
MAY_IMPORT = {"ashley.api.connection_settings", "ashley.wiring", "ashley.connections.settings_write_postgres"}


def imported(tree: ast.Module, module: str) -> set[str]:
    """Every dotted name `module`'s imports could name: the module imported, and for `from m import x` also `m.x`, since
    `x` may be a module. Relative imports are resolved against `module`."""
    parts = module.split(".")
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = parts[: len(parts) - node.level] if node.level else []
            target = ".".join(base + (node.module.split(".") if node.module else []))
            out |= {target, *(f"{target}.{a.name}" for a in node.names)}
    return out


def writers_imported_by(modules: dict[str, ast.Module]) -> dict[str, set[str]]:
    return {m: found for m, tree in modules.items() if (found := imported(tree, m) & WRITERS)}


def test_only_the_member_route_and_the_wiring_import_the_settings_writer(python_tree: dict[Path, Parsed]) -> None:
    modules = {dotted(p): file.tree for p, file in package(python_tree).items()}
    found = writers_imported_by(modules)
    assert found, "the gate saw no importer of the writer: it would pass on nothing"
    assert set(found) == MAY_IMPORT, f"importers of the settings writer: {sorted(found)}, allowed {sorted(MAY_IMPORT)}"


def test_the_gate_catches_a_tool_a_channel_or_a_model_call_importing_the_writer() -> None:
    planted = {
        "ashley.tools.planted": "from ..connections.settings_write import SettingsWriter\n",
        "ashley.channels.planted": "from ..connections import settings_write\n",
        "ashley.inference.planted": "import ashley.connections.settings_write_postgres\n",
        "ashley.tools.deep.planted": "from ...connections.settings_write_postgres import PostgresSettingsWriter\n",
        "ashley.tools.clean": "from ..connections.settings_read import SettingsReader\n"}
    found = writers_imported_by({m: ast.parse(src) for m, src in planted.items()})
    assert set(found) == set(planted) - {"ashley.tools.clean"}, found


def test_the_writer_modules_exist_where_the_gate_names_them() -> None:
    for name in WRITERS:
        assert (PKG.parent / (name.replace(".", "/") + ".py")).is_file(), name
