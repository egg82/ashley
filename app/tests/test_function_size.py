"""No function grows past LIMIT lines: large functions are where bugs hide. Functions
already over it are held in tools/held/function_size.json as `{file: {qualified name:
lines}}` through the shared ledger (tools/held_ledger.py). A new long function, or a
held one that grew, fails naming it. One that shrank or went fails as stale, so a
split in one place cannot pay for a new long function in another, even under the same
name. `python tests/test_function_size.py --write` rewrites the ledger; never run it
to let a longer function through.

Template from the agentic-engineering skill: set SRC to the package directories, then
seed with --write once."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from held_ledger import Ledger, dump, load, problems, total
from source_tree import SRC, Parsed, parse_tree, rel

HELD = ROOT / "tools" / "held" / "function_size.json"
LIMIT = 80


def sizes(tree: ast.Module) -> dict[str, int]:
    """Lines of every function over LIMIT in one parsed file, by qualified name
    (`Class.method`, `outer.inner`); a repeated name in one scope takes `#2`, `#3` in
    source order."""
    out: dict[str, int] = {}
    seen: set[str] = set()

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):  # a def is a statement, never inside one; skipping them keeps this fast
                continue
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{scope}.{child.name}" if scope else child.name
                n = 1
                while name in seen:
                    n += 1
                    name = f"{scope}.{child.name}#{n}" if scope else f"{child.name}#{n}"
                seen.add(name)
                if not isinstance(child, ast.ClassDef):
                    lines = (child.end_lineno or child.lineno) - child.lineno + 1
                    if lines > LIMIT:
                        out[name] = lines
                walk(child, name)
            else:
                walk(child, scope)

    walk(tree, "")
    return out


def source_sizes(source: str) -> dict[str, int]:
    return sizes(ast.parse(source))


def counted(parsed: dict[Path, Parsed]) -> Ledger:
    ledger: Ledger = {}
    for p, file in parsed.items():
        found = sizes(file.tree)
        if found:
            ledger[rel(p)] = found
    return ledger


FIX = f"over {LIMIT} lines and not held: split it"
WRITE = "python tests/test_function_size.py --write"


def test_the_gate_sees_the_code(python_tree: dict[Path, Parsed]):
    assert python_tree, f"no .py files under {SRC}: the gate would pass on nothing"


def test_the_held_ledger_is_what_the_code_is(python_tree: dict[Path, Parsed]):
    wrong = problems(counted(python_tree), load(HELD), FIX, WRITE)
    assert not wrong, "\n".join(wrong)


def test_this_test_can_fail():
    """Controls: a long function is found, twins get distinct names, a swap fails twice
    at an equal total, a shrink is stale."""
    body = "".join(f"    x = {i}\n" for i in range(LIMIT))
    assert list(source_sizes(f"def f():\n{body}")) == ["f"]
    assert source_sizes(f"def f():\n{body[: -len('    x = 0') - 2]}") == {}
    method_body = body.replace("    x", "        x")
    twin = f"def plan():\n{body}class V:\n    def plan(self):\n{method_body}"
    assert sorted(source_sizes(twin)) == ["V.plan", "plan"]
    assert sorted(source_sizes(f"def f():\n{body}def f():\n{body}")) == ["f", "f#2"]
    held = {"a.py": {"plan": LIMIT + 1}}
    assert problems(held, held, "", "") == []
    swapped = {"a.py": {"V.plan": LIMIT + 1}}
    assert len(problems(swapped, held, "", "")) == 2 and total(swapped) == total(held)
    assert "stale, lower it" in problems(held, {"a.py": {"plan": LIMIT + 9}}, "", "")[0]


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        HELD.parent.mkdir(parents=True, exist_ok=True)
        ledger = counted(parse_tree())
        HELD.write_text(dump(ledger))
        print(
            f"wrote {HELD.relative_to(ROOT)}: "
            f"{len(ledger)} files, {total(ledger)} lines held"
        )
