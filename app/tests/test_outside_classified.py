"""The classification gate: every `ToolSpec(` call in `app/ashley` states `outside=`, every one that is not a read (nor a
tool that takes an agreement) states `tier=`, and every `Inbound(` call states `taint=`, so whoever adds a tool or a woken
turn decides what it reads, what a tainted turn does with it, or where it came from. The scan is `ast`, and it proves it
can fail on a planted call and that it read something."""

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from source_tree import Parsed

PACKAGE = Path(__file__).resolve().parent.parent / "ashley"
FLOORS = {"ToolSpec": 50, "Inbound": 10}
TIER_FLOOR = 30
KEYWORD = {"ToolSpec": "outside", "Inbound": "taint"}

Call = tuple[str, int, bool]  # (where, line, states its keyword)


def package_trees(package_tree: Mapping[Path, Parsed]) -> Iterator[tuple[str, ast.Module]]:
    """Each module of `app/ashley` as its path within the package and its parsed tree."""
    return ((str(p.relative_to(PACKAGE)), parsed.tree) for p, parsed in package_tree.items() if PACKAGE in p.parents)


def calls(tree: ast.Module, name: str, where: str = "") -> list[Call]:
    """Every call to `name` in `tree`, with whether it passes its classifying keyword."""
    keyword = KEYWORD[name]
    return [(where, n.lineno, any(k.arg == keyword for k in n.keywords)) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]


def _is_true(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def unrated(tree: ast.Module) -> list[tuple[int, bool]]:
    """Every `ToolSpec(` call in `tree` that is not a read (`reads=True`, or True as its fourth argument) and does not
    take an agreement (`agrees=True`), with whether it passes `tier=`."""
    found: list[tuple[int, bool]] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ToolSpec"):
            continue
        reads = any(k.arg == "reads" and _is_true(k.value) for k in n.keywords) or (len(n.args) >= 4 and _is_true(n.args[3]))
        agrees = any(k.arg == "agrees" and _is_true(k.value) for k in n.keywords)
        if not reads and not agrees:
            found.append((n.lineno, any(k.arg == "tier" for k in n.keywords)))
    return found


def unstated(tree: ast.Module, name: str) -> list[int]:
    """The lines of calls to `name` in `tree` that do not pass its classifying keyword."""
    return [line for _, line, stated in calls(tree, name) if not stated]


@pytest.fixture(scope="module")
def package(package_tree: Mapping[Path, Parsed]) -> dict[str, list[Call]]:
    """Every classified call in `app/ashley`, by name. Built once for the module: the time gate does not time a fixture."""
    found: dict[str, list[Call]] = {name: [] for name in KEYWORD}
    for where, tree in package_trees(package_tree):
        for name in KEYWORD:
            found[name] += calls(tree, name, where)
    return found


def check(found: list[Call], name: str) -> None:
    assert len(found) >= FLOORS[name], f"read {len(found)} {name} calls: the scan sees too little"
    wrong = [f"{where}:{line}" for where, line, stated in found if not stated]
    assert not wrong, f"{name} without {KEYWORD[name]}=: {wrong}"


def test_every_tool_spec_states_whether_its_results_can_carry_outside_words(package: dict[str, list[Call]]) -> None:
    check(package["ToolSpec"], "ToolSpec")


def test_every_change_states_its_tier(package_tree: Mapping[Path, Parsed]) -> None:
    found = [(where, line, stated) for where, tree in package_trees(package_tree) for line, stated in unrated(tree)]
    assert len(found) >= TIER_FLOOR, f"read {len(found)} changes: the scan sees too little"
    wrong = [f"{where}:{line}" for where, line, stated in found if not stated]
    assert not wrong, f"a change's ToolSpec without tier=: {wrong}"


def test_the_tier_scan_fails_on_a_planted_change_and_passes_a_read_an_agreement_and_a_rated_change() -> None:
    planted = ('a = ToolSpec("x", "d", {}, outside=False)\nb = ToolSpec("y", "d", {}, True, outside=False)\n'
               'c = ToolSpec("z", "d", {}, outside=False, agrees=True)\nd = ToolSpec("w", "d", {}, outside=False, tier="runs")\n'
               'e = ToolSpec("v", "d", {}, reads=True, outside=True)\n')
    assert unrated(ast.parse(planted)) == [(1, False), (4, True)]


def test_every_inbound_states_what_outside_started_it(package: dict[str, list[Call]]) -> None:
    check(package["Inbound"], "Inbound")


def test_the_scan_fails_on_a_planted_unclassified_spec_and_inbound() -> None:
    planted = 'a = ToolSpec("x", "d", {})\nb = Inbound(1, "t")\nc = ToolSpec("y", "d", {}, outside=False)\n'
    made = ast.parse(planted)
    assert unstated(made, "ToolSpec") == [1]
    assert unstated(made, "Inbound") == [2]
    assert unstated(ast.parse("c = ToolSpec('y', 'd', {}, outside=True)\nd = Inbound(1, taint=None)\n"), "ToolSpec") == []
    assert len(calls(made, "ToolSpec")) == 2, "control: the planted source has two specs"
