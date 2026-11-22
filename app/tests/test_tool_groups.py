"""Every group of tools a turn can offer has the one line the loader tool tells her about it (`channels.tool_groups`),
and no line is left for a group `turn_tools` no longer offers."""

import ast
from pathlib import Path

from ashley.channels import tool_groups, turn_tools

INNER = {"turn", "arrange", "feed"}
"""Keys of `turn_tools` that are not groups a turn offers: the wrapper of a narrowed turn and the screen's two halves."""


def keys(source: str) -> set[str]:
    """The string keys `turn_tools` files sources under: dict-literal keys and `found["key"]` assignments."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            found.update(k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "found" \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            found.add(node.slice.value)
    return found


def groups() -> set[str]:
    source = Path(turn_tools.__file__).read_text()
    constants = {turn_tools.EVERYDAY, turn_tools.READERS, turn_tools.ERRAND, turn_tools.METHOD}
    return (keys(source) | constants) - INNER


def test_every_group_a_turn_can_offer_has_a_line() -> None:
    offered = groups()
    assert len(offered) > 30 and {"mail", "money", "screen", "bench_run", "home"} <= offered
    assert offered - set(tool_groups.SUMMARY) == set()


def test_no_line_is_left_for_a_group_no_turn_offers() -> None:
    assert set(tool_groups.SUMMARY) - groups() == set()


def test_the_scan_sees_a_key_in_each_shape() -> None:
    assert keys('found["a"] = 1\nx = {"b": 1}\ny = f(**{"c": 2})\nz = found[name]\n') == {"a", "b", "c"}
