"""Nothing she does on her own can widen what she trusts or reset what her household set: the modules that write a
connection's settings (`ashley.connections.settings_write` and the Postgres writer), a household's own fields
(`ashley.people.household_write` and its Postgres writer), its persona overrides (`ashley.skills.persona_write` and
its Postgres writer) and its model choices (`ashley.inference.route_choice_write` and its Postgres writer) are imported
only by their person route and the wiring that registers them, so no tool, channel or model call can reach
`SettingsWriter`, `HouseholdWriter`, `PersonaWriter` or `RouteChoiceWriter` (`decisions.md`, "A connection has settings
its person sets", "A household may override her taste, never her contract", "A household chooses the model for its
chat"). Who is an admin (`ashley.people.admins` and its Postgres writer) is written only by the people and sign-in routes
and the wiring ("An admin changes what the deployment shares"). An import of any by another module fails here, whatever
package it is in."""

import ast
from pathlib import Path

import pytest
from source_tree import Parsed
from test_boundaries import PKG, dotted, package

GUARDED: dict[str, tuple[set[str], set[str]]] = {
    "settings": ({"ashley.connections.settings_write", "ashley.connections.settings_write_postgres"},
                 {"ashley.api.connection_settings", "ashley.wiring", "ashley.connections.settings_write_postgres"}),
    "household": ({"ashley.people.household_write", "ashley.people.postgres_household_write"},
                  {"ashley.api.household", "ashley.wiring", "ashley.people.postgres_household_write"}),
    "persona": ({"ashley.skills.persona_write", "ashley.skills.postgres_persona_write"},
                {"ashley.api.persona", "ashley.wiring_skills", "ashley.skills.postgres_persona_write"}),
    "routes": ({"ashley.inference.route_choice_write", "ashley.inference.postgres_route_choice_write"},
               {"ashley.api.spend_routes", "ashley.wiring_inference", "ashley.inference.postgres_route_choice_write"}),
    "admins": ({"ashley.people.admins", "ashley.people.postgres_admins"},
               {"ashley.api.people", "ashley.api.signin", "ashley.wiring", "ashley.people.postgres_admins"}),
}


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


def writers_imported_by(modules: dict[str, ast.Module], writers: set[str]) -> dict[str, set[str]]:
    return {m: found for m, tree in modules.items() if (found := imported(tree, m) & writers)}


@pytest.mark.parametrize("guarded", sorted(GUARDED))
def test_only_the_person_route_and_the_wiring_import_a_writer(python_tree: dict[Path, Parsed], guarded: str) -> None:
    writers, may_import = GUARDED[guarded]
    modules = {dotted(p): file.tree for p, file in package(python_tree).items()}
    found = writers_imported_by(modules, writers)
    assert found, "the gate saw no importer of the writer: it would pass on nothing"
    assert set(found) == may_import, f"importers of the {guarded} writer: {sorted(found)}, allowed {sorted(may_import)}"


def test_the_gate_catches_a_tool_a_channel_or_a_model_call_importing_a_writer() -> None:
    planted = {
        "ashley.tools.planted": "from ..connections.settings_write import SettingsWriter\n",
        "ashley.channels.planted": "from ..connections import settings_write\n",
        "ashley.inference.planted": "import ashley.connections.settings_write_postgres\n",
        "ashley.tools.deep.planted": "from ...connections.settings_write_postgres import PostgresSettingsWriter\n",
        "ashley.tools.household": "from ..people.household_write import HouseholdWriter\n",
        "ashley.persona.household": "from ..people import postgres_household_write\n",
        "ashley.tools.clean": "from ..connections.settings_read import SettingsReader\n",
        "ashley.tools.reads": "from ..people.people import People\n",
        "ashley.tools.persona": "from ..skills.persona_write import PersonaWriter\n",
        "ashley.channels.persona": "from ..skills import postgres_persona_write\n",
        "ashley.tools.persona_reads": "from ..skills.persona import PersonaOverrides\n",
        "ashley.tools.routes": "from ..inference.route_choice_write import RouteChoiceWriter\n",
        "ashley.channels.routes": "from ..inference import postgres_route_choice_write\n",
        "ashley.inference.router_planted": "from .route_choice_write import RouteChoiceWriter\n",
        "ashley.tools.route_reads": "from ..inference.route_choices import RouteChoiceReads\n"}
    writers = {name for names, _ in GUARDED.values() for name in names}
    found = writers_imported_by({m: ast.parse(src) for m, src in planted.items()}, writers)
    assert set(found) == set(planted) - {"ashley.tools.clean", "ashley.tools.reads", "ashley.tools.persona_reads",
                                         "ashley.tools.route_reads"}, found


def test_the_writer_modules_exist_where_the_gate_names_them() -> None:
    for writers, _ in GUARDED.values():
        for name in writers:
            assert (PKG.parent / (name.replace(".", "/") + ".py")).is_file(), name
