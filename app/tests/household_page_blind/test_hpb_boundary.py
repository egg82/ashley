"""Writes go only through the person route: nothing a model, tool or channel runs can import the household writer."""

import ast
from pathlib import Path

from source_tree import Parsed
from test_boundaries import PKG, dotted, package
from test_settings_boundary import writers_imported_by

WRITERS = {"ashley.people.household_write", "ashley.people.postgres_household_write"}
ROUTE_AND_WIRING = {"ashley.api.household", "ashley.wiring", "ashley.people.postgres_household_write"}


def test_only_the_household_route_and_the_wiring_import_the_writer(package_tree: dict[Path, Parsed]) -> None:
    modules = {dotted(p): file.tree for p, file in package(package_tree).items()}
    found = writers_imported_by(modules, WRITERS)
    assert found, "the gate saw no importer of the writer: it would pass on nothing"
    assert set(found) == ROUTE_AND_WIRING, sorted(found)


def test_no_tool_channel_or_inference_module_imports_the_writer(package_tree: dict[Path, Parsed]) -> None:
    modules = {dotted(p): file.tree for p, file in package(package_tree).items()}
    found = writers_imported_by(modules, WRITERS)
    reaching = [m for m in found if m.startswith(("ashley.tools", "ashley.channels", "ashley.inference", "ashley.persona"))]
    assert reaching == []
    assert any(m.startswith("ashley.tools") for m in modules), "no tool modules were scanned"


def test_the_gate_catches_a_planted_importer() -> None:
    planted = {"ashley.tools.planted": "from ..people.household_write import HouseholdWriter\n",
               "ashley.channels.deep.planted": "from ...people import postgres_household_write\n",
               "ashley.tools.reads": "from ..people.people import People\n"}
    found = writers_imported_by({m: ast.parse(src) for m, src in planted.items()}, WRITERS)
    assert set(found) == {"ashley.tools.planted", "ashley.channels.deep.planted"}


def test_the_writer_modules_exist() -> None:
    for name in WRITERS:
        assert (PKG.parent / (name.replace(".", "/") + ".py")).is_file(), name
