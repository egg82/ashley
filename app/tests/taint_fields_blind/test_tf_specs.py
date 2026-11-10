"""`ToolSpec.outside` (true unless stated), `ToolResult.outside` (null unless a tool sets it), the classification of
today's tools, and the gate that makes whoever adds a tool or a turn decide."""

import ast
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from ashley.channels import aside
from ashley.inference.model import ToolResult, ToolSpec
from source_tree import Parsed
from taint_fields_blind_support import OBJ, SPECS, located_specs, missing_keyword, scan

OUTSIDE_TOOLS = (
    "look_up", "read_page", "find_places", "search_printables", "printables_files", "git_projects", "git_tree",
    "git_read_file", "claude_read", "house_ask", "money_transactions", "bench_frames", "bench_transcribe",
    "bench_read", "bench_read_piece", "bench_shelf", "bench_look")
HOUSEHOLD_TOOLS = (
    "house_state", "house_find", "house_history", "house_automations", "house_automation", "money_accounts",
    "money_categories", "money_net_worth", "reminders", "household_devices", "claude_sessions", "skill_read",
    "bench_install_state", "bench_run", "bench_last_run", "run_code", "house_do", "house_change", "remind",
    "claude_prompt")
FLOOR = 18


@pytest.mark.parametrize("reads", [True, False])
def test_a_spec_that_says_nothing_taints(reads: bool) -> None:
    assert ToolSpec("t", "d", OBJ, reads=reads).outside is True


@pytest.mark.parametrize("stated", [True, False])
def test_a_spec_keeps_what_it_states(stated: bool) -> None:
    assert ToolSpec("t", "d", OBJ, reads=True, outside=stated).outside is stated


def test_a_result_says_nothing_unless_its_tool_sets_it() -> None:
    assert ToolResult("c1", "{}").outside is None


@pytest.mark.parametrize("stated", [True, False])
def test_a_result_keeps_what_its_tool_sets(stated: bool) -> None:
    assert ToolResult("c1", "{}", outside=stated).outside is stated
    assert ToolResult("c1", "{}", outside=stated) != ToolResult("c1", "{}"), "control: it is part of the result"


def test_a_spec_keeps_its_outside_when_aside_is_added() -> None:
    offered = {t.name: t for t in aside.offered(SPECS)}
    assert {n: t.outside for n, t in offered.items()} == {t.name: t.outside for t in SPECS}
    assert any(not t.outside for t in SPECS) and any(t.outside for t in SPECS), "control: both values are in play"
    assert offered["lamp_state"].parameters != OBJ, "control: the spec was rebuilt to add the aside"


def test_a_copy_of_a_spec_keeps_its_outside() -> None:
    assert replace(SPECS[0], description="x").outside is False


def test_every_tool_the_spec_names_as_outside_taints(python_tree: Mapping[Path, Parsed]) -> None:
    found = located_specs(python_tree)
    seen = [n for n in OUTSIDE_TOOLS if n in found]
    assert seen, "the scan located none of them"
    assert [n for n in seen if found[n] is not True] == []


def test_every_tool_the_spec_names_as_household_does_not_taint(python_tree: Mapping[Path, Parsed]) -> None:
    found = located_specs(python_tree)
    seen = [n for n in HOUSEHOLD_TOOLS if n in found]
    assert seen, "the scan located none of them"
    assert [n for n in seen if found[n] is not False] == []


def test_the_scans_locate_enough_of_the_named_tools_to_mean_something(python_tree: Mapping[Path, Parsed]) -> None:
    found = located_specs(python_tree)
    assert len([n for n in (*OUTSIDE_TOOLS, *HOUSEHOLD_TOOLS) if n in found]) >= FLOOR


def test_the_scan_flags_a_toolspec_that_does_not_state_outside() -> None:
    source = ('ToolSpec("a", "d", {})\n'
              'ToolSpec("b", "d", {}, outside=False)\n'
              'ToolSpec("c", "d", {}, True, True)\n'
              'ToolSpec("d", "d", {}, **extra)\n')
    assert missing_keyword(ast.parse(source), "ToolSpec", "outside", 5) == (4, [1])


def test_the_scan_flags_an_inbound_that_does_not_state_taint() -> None:
    source = 'Inbound(1, "t")\nInbound(1, "t", taint=None)\nInbound(**fields)\n'
    assert missing_keyword(ast.parse(source), "Inbound", "taint") == (3, [1])


def test_every_toolspec_in_the_app_states_outside(python_tree: Mapping[Path, Parsed]) -> None:
    total, bad = scan(python_tree, "ToolSpec", "outside", 5)
    assert total >= 40, "the scan read too few call sites to mean anything"
    assert bad == []


def test_every_inbound_in_the_app_states_taint(python_tree: Mapping[Path, Parsed]) -> None:
    total, bad = scan(python_tree, "Inbound", "taint")
    assert total >= 8, "the scan read too few call sites to mean anything"
    assert bad == []
