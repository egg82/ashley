"""Pins that nothing she does on her own can write persona overrides: `ashley.skills.persona_write` is imported only by
the persona route and the wiring (and the module that implements it, in `ashley.skills`), as `test_settings_boundary`
holds for the other person-only writers; the read module never imports the writer; and the wire models take the
refusal reason from the read module."""

import ast
from pathlib import Path

from source_tree import Parsed
from test_boundaries import PKG, dotted, package
from test_settings_boundary import writers_imported_by

WRITER = "ashley.skills.persona_write"
ROUTE_AND_WIRING = {"ashley.api.persona", "ashley.wiring", "ashley.wiring_skills"}


def importers(python_tree: dict[Path, Parsed]) -> dict[str, set[str]]:
    modules = {dotted(p): file.tree for p, file in package(python_tree).items()}
    return writers_imported_by(modules, {WRITER})


def outside_the_implementation(found: dict[str, set[str]]) -> set[str]:
    return {m for m in found if not m.startswith("ashley.skills.") or m == "ashley.skills.persona"}


def test_only_the_persona_route_the_wiring_and_the_implementation_import_the_writer(
        python_tree: dict[Path, Parsed]) -> None:
    found = importers(python_tree)
    assert found, "the gate saw no importer of the persona writer: it would pass on nothing"
    assert outside_the_implementation(found) <= ROUTE_AND_WIRING, sorted(found)
    assert found.keys() & {"ashley.wiring", "ashley.wiring_skills"}, "the wiring no longer registers the writer"


def test_no_tool_channel_or_model_call_module_imports_the_writer(python_tree: dict[Path, Parsed]) -> None:
    found = importers(python_tree)
    assert found
    for module in found:
        assert not module.startswith(("ashley.tools", "ashley.channels", "ashley.inference", "ashley.persona",
                                      "ashley.conversations", "ashley.memory", "ashley.errands")), module


def test_the_read_module_and_the_wire_models_do_not_import_the_writer(python_tree: dict[Path, Parsed]) -> None:
    found = importers(python_tree)
    assert found
    assert "ashley.skills.persona" not in found
    assert "ashley.api.persona_models" not in found


def test_the_gate_catches_a_planted_importer() -> None:
    planted = {
        "ashley.tools.planted": "from ..skills.persona_write import PersonaWriter\n",
        "ashley.channels.planted": "from ..skills import persona_write\n",
        "ashley.inference.planted": "import ashley.skills.persona_write\n",
        "ashley.tools.clean": "from ..skills.persona import PersonaOverrides\n",
    }
    found = writers_imported_by({m: ast.parse(src) for m, src in planted.items()}, {WRITER})
    assert set(found) == set(planted) - {"ashley.tools.clean"}


def test_the_writer_module_exists_where_the_gate_names_it() -> None:
    assert (PKG.parent / (WRITER.replace(".", "/") + ".py")).is_file()
