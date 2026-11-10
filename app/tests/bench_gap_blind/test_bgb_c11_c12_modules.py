"""Contracts 11, 12 and 13's modules: bench-act grades by step type and tool names and covers E1-E8; no module that
carries a new branch imports a regex; `tools/bench_outcomes.py` exists. Imports are plain: a missing module fails
collection here, never skips."""

import ast
import json
from importlib import resources
from pathlib import Path
from types import ModuleType

import pytest
from ashley.channels import aside, tool_loop
from ashley.evals import __main__ as evals_main
from ashley.evals import bench_act
from ashley.tools import bench_outcomes


def imports(module: ModuleType) -> set[str]:
    source = Path(str(module.__file__)).read_text()
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module", [aside, tool_loop, bench_outcomes, bench_act])
def test_c12_no_module_with_a_new_branch_imports_a_regex(module: ModuleType) -> None:
    assert "re" not in imports(module)


def test_c11_the_cases_file_names_every_case_e1_to_e8() -> None:
    text = resources.files("ashley.evals").joinpath("bench_act_cases.json").read_text()
    json.loads(text)
    for n in range(1, 9):
        assert f"E{n}" in text


def test_c11_bench_act_is_registered_with_the_evals() -> None:
    assert "bench_act" in Path(str(evals_main.__file__)).read_text()


def test_c13_bench_outcomes_is_a_module_of_the_tools_package() -> None:
    assert Path(str(bench_outcomes.__file__)).parent.name == "tools"
