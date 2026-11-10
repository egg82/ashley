"""Support for the blind tests of the taint fields (`docs/decisions.md`, "A turn that has read outside words asks before
it changes anything", its first part): the guesses the suite makes, the tools a turn can read, and the scans that
locate today's specs and call sites. Every guess lives in ASSUMPTIONS."""

import ast
import importlib
import pkgutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import ashley.tools as tools_package
from ashley.inference.model import ToolResult, ToolSpec
from ashley.tools import code_host
from source_tree import Parsed

ASSUMPTIONS = {
    "A1": "Inbound.taint is a keyword field with default None and the values watch, stranger "
          "(spec: 'either null or one of watch or stranger'; 'taint's null default is for tests').",
    "A2": "Checkpoint.tainted is a keyword field, default None, holding the tool NAME as a str "
          "(spec: 'the name of the first tool whose result tainted the turn, or null').",
    "A3": "Checkpoint JSON keys are the field names ('tainted', and 'taint' inside 'inbound'), and a checkpoint "
          "an older pod saved without them loads as untainted (spec: 'What survives a failover: everything'; "
          "existing loads() uses raw.get for later fields).",
    "A4": "Steps.tainted(tool) is a coroutine taking the tool name; the base Steps and NO_STEPS record nothing "
          "(spec: 'Steps gains tainted(tool)'; 'the base records nothing').",
    "A5": "Saved.tainted(tool) saves the checkpoint with tainted set and raises ClaimLost when the claim is gone "
          "(spec: 'saves it and renews the claim ... A runner that loses the turn at that moment raises, as "
          "starting does').",
    "A6": "Whatever decides that a result taints (loop or decorator), a person turn on a saved channel ends with "
          "Checkpoint.tainted set in the stored checkpoint BEFORE the next model step is asked (spec: 'before the "
          "tainting result goes back to the loop').",
    "A7": "An origin-tainted turn (Inbound.taint set) is tainted by the Inbound alone; the suite never asserts what "
          "Checkpoint.tainted holds for it, only that Inbound.taint survives in the stored checkpoint.",
    "A8": "A call to a name outside the catalogue taints the turn and tainted holds that name (spec: 'A name not in "
          "the catalogue taints').",
    "A9": "Only the FIRST tainting tool is kept: tainted never changes once set (spec: 'the name of the first tool', "
          "'a taint never clears').",
    "A10": "A discord guild message whose author maps to no person is 'stranger'; one whose author is a person is "
           "null; a DM and every other turn builder named in the spec are null. A person of ANOTHER household "
           "writing in a guild is not asserted.",
    "A11": "The gate is the scan the spec describes: every ToolSpec( call passes outside= (keyword, 5th positional "
           "or a ** splat) and every Inbound( call passes taint= (keyword or splat), over app/ashley.",
    "A12": "Today's specs are located from module-level ToolSpec values of ashley.tools.*, code_host.specs and "
           "ToolSpec( calls with a literal outside=; a table tool the scans cannot locate is not asserted, and a "
           "floor says how many must be found.",
    "A13": "A tool result that is cut (tools.cut) keeps its own outside value.",
}

APP = Path(__file__).resolve().parents[2]
PLAIN = "plain"
INSIDE = "lamp_state"
OUTSIDE = "fetch"
OUTSIDE_TOO = "fetch_more"
NARROWED = "narrowed"
WIDENED = "widened"
CHANGE = "switch"
UNSTATED_CHANGE = "toggle"
BIG = "big"
GHOST = "ghost"
OBJ: Mapping[str, object] = {"type": "object"}

SPECS = (
    ToolSpec(INSIDE, "a household read", OBJ, reads=True, outside=False),
    ToolSpec(OUTSIDE, "an outside read", OBJ, reads=True, outside=True),
    ToolSpec(OUTSIDE_TOO, "another outside read", OBJ, reads=True, outside=True),
    ToolSpec(PLAIN, "a read that says nothing", OBJ, reads=True),
    ToolSpec(NARROWED, "outside tool, clean result", OBJ, reads=True, outside=True),
    ToolSpec(WIDENED, "household tool, dirty result", OBJ, reads=True, outside=False),
    ToolSpec(CHANGE, "a change", OBJ, reads=False, outside=False),
    ToolSpec(UNSTATED_CHANGE, "a change that says nothing", OBJ, reads=False),
    ToolSpec(BIG, "an outside read with a long result", OBJ, reads=True, outside=True),
)


def result_of(call_id: str, name: str) -> ToolResult:
    """What the fake tools return: the result's own `outside` is set only by NARROWED and WIDENED."""
    if name == NARROWED:
        return ToolResult(call_id, '{"ok": true}', outside=False)
    if name == WIDENED:
        return ToolResult(call_id, '{"ok": true}', outside=True)
    if name == BIG:
        return ToolResult(call_id, "x" * 1_000_000)
    return ToolResult(call_id, f'{{"ran": "{name}"}}')


def package_files(python_tree: Mapping[Path, Parsed]) -> Iterator[tuple[Path, Parsed]]:
    """The parsed modules of app/ashley, in path order."""
    return ((p, parsed) for p, parsed in python_tree.items() if APP / "ashley" in p.parents)


def missing_keyword(tree: ast.Module, callee: str, keyword: str, positional: int | None = None) -> tuple[int, list[int]]:
    """(calls of `callee` in `tree`, the lines of those that pass neither `keyword=`, a ** splat nor `positional`
    positional arguments)."""
    seen = 0
    bad: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == callee:
            seen += 1
            stated = any(k.arg in (keyword, None) for k in node.keywords)
            if not stated and not (positional is not None and len(node.args) >= positional):
                bad.append(node.lineno)
    return seen, bad


def scan(python_tree: Mapping[Path, Parsed], callee: str, keyword: str,
         positional: int | None = None) -> tuple[int, list[str]]:
    """The scan of app/ashley: how many `callee(` calls it read and which pass no `keyword`."""
    total = 0
    bad: list[str] = []
    for path, parsed in package_files(python_tree):
        if callee not in parsed.source:
            continue
        seen, lines = missing_keyword(parsed.tree, callee, keyword, positional)
        total += seen
        bad += [f"{path.relative_to(APP)}:{n}" for n in lines]
    return total, bad


def specs_in(value: Any) -> list[ToolSpec]:
    """The ToolSpecs `value` is, or holds when it is a tuple or list."""
    if isinstance(value, ToolSpec):
        return [value]
    items: tuple[Any, ...] = tuple(value) if type(value) in (tuple, list) else ()
    return [i for i in items if isinstance(i, ToolSpec)]


def located_specs(python_tree: Mapping[Path, Parsed]) -> dict[str, bool | None]:
    """Tool name to its stated `outside` for the specs the scans can see; None when the value is the default."""
    found: dict[str, bool | None] = {}
    for info in pkgutil.iter_modules(tools_package.__path__):
        module = importlib.import_module(f"ashley.tools.{info.name}")
        for value in vars(module).values():
            found.update({s.name: s.outside for s in specs_in(value)})
    for spec in code_host.specs(("gitlab",), True):
        found[spec.name] = spec.outside
    for path, parsed in package_files(python_tree):
        if "ToolSpec" not in parsed.source:
            continue
        module_name = ".".join(path.relative_to(APP).with_suffix("").parts)
        for node in ast.walk(parsed.tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ToolSpec" and node.args:
                stated = {k.arg: k.value for k in node.keywords}.get("outside")
                name = node.args[0]
                if isinstance(stated, ast.Constant) and isinstance(stated.value, bool):
                    if isinstance(name, ast.Constant) and isinstance(name.value, str):
                        found.setdefault(name.value, stated.value)
                    elif isinstance(name, ast.Name):
                        value = getattr(importlib.import_module(module_name), name.id, None)
                        if isinstance(value, str):
                            found.setdefault(value, stated.value)
    return found
