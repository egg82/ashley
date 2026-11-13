"""Each tool's `outside`, as `decisions.md` ("A turn that has read outside words asks before it does anything consequential the person did not ask for")
classifies it. Names are read from the specs' own source; a spec whose name is built at run time is not here."""

import ast
import importlib
from collections.abc import Mapping
from pathlib import Path

import pytest
from source_tree import Parsed

PACKAGE = Path(__file__).resolve().parent.parent / "ashley"

OUTSIDE = {
    "look_up", "read_page", "printables_files", "git_projects", "git_tree", "git_read_file", "claude_read", "house_ask",
    "money_transactions", "bench_frames", "bench_transcribe", "bench_read", "bench_read_piece", "bench_shelf",
    "bench_look", "watch", "mail_search", "mail_read", "send_readers", "discord_recent",
}
OWN = {
    "house_state", "house_find", "house_history", "house_automations", "house_automation", "money_accounts",
    "money_categories", "money_net_worth", "reminders", "household_devices", "claude_sessions", "skill_read",
    "bench_install_state", "bench_run", "bench_last_run", "run_code", "house_do", "house_change", "house_confirm",
    "claude_prompt", "bench_add", "bench_edit", "bench_remove", "unwatch", "watches", "arm_reminder", "mail_boxes",
    "mail_labels", "mail_draft", "mail_label", "mail_send",
}


def named(path: Path, first: ast.expr) -> str | None:
    """The name a spec is built with: a string, or a string constant of its module."""
    if isinstance(first, ast.Constant):
        return first.value if isinstance(first.value, str) else None
    module = importlib.import_module("ashley." + ".".join(path.relative_to(PACKAGE).with_suffix("").parts))
    value = getattr(module, first.id, None) if isinstance(first, ast.Name) else None
    return value if isinstance(value, str) else None


@pytest.fixture(scope="module")
def found(package_tree: Mapping[Path, Parsed]) -> dict[str, bool]:
    """Every spec whose name is a string, or a module constant, and its `outside`. Built once for the module."""
    table: dict[str, bool] = {}
    for path, parsed in package_tree.items():
        if PACKAGE not in path.parents:
            continue
        for n in ast.walk(parsed.tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ToolSpec":
                name = named(path, n.args[0])
                flag = next((k.value for k in n.keywords if k.arg == "outside"), None)
                if name is not None and isinstance(flag, ast.Constant):
                    table[name] = bool(flag.value)
    return table


BUILT_AT_RUN_TIME = {"git_projects", "git_tree", "git_read_file"}


def test_the_scan_reads_the_specs(found: dict[str, bool]) -> None:
    assert len(found) >= 60


@pytest.mark.parametrize("name", sorted(OUTSIDE - BUILT_AT_RUN_TIME))
def test_a_tool_whose_results_carry_outside_words_taints(name: str, found: dict[str, bool]) -> None:
    assert found[name] is True


@pytest.mark.parametrize("name", sorted(OWN))
def test_a_tool_that_returns_the_households_own_records_or_its_own_confirmation_does_not(name: str, found: dict[str, bool]) -> None:
    assert found[name] is False


def test_nothing_else_taints(found: dict[str, bool]) -> None:
    assert {n for n, outside in found.items() if outside} <= OUTSIDE
