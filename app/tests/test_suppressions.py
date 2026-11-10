"""Suppressions are a held count, not an escape hatch: a `# pyright: ignore`, `# type: ignore`, `# noqa` or a
`typing.cast` removes an error the way a fix does, and nothing else tells them apart. Each is counted per file in
tools/held/suppressions.json, which may only shrink, and must name its rule and a reason on its line:
`# pyright: ignore[reportX] - why`. Never cast to quiet a safety type. `python tests/test_suppressions.py --write`
rewrites the ledger; never run it to let one through."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from held_ledger import Ledger, dump, load, problems, tally, total
from source_tree import Parsed, comments_of, parse_tree, rel

HELD = ROOT / "tools" / "held" / "suppressions.json"
MARKER = re.compile(r"#\s*(pyright:\s*ignore|type:\s*ignore|noqa)\b")
NAMED = re.compile(r"#\s*(pyright:\s*ignore\[[\w, ]+\]|type:\s*ignore\[[\w, -]+\]|noqa:\s*[A-Z]+\d+)\s+-\s+\S")
FIX = "a new suppression: fix the error instead, or name the rule and a reason and report it"
WRITE = "python tests/test_suppressions.py --write"


def marked(file: Parsed) -> list[tuple[int, str, str]]:
    return [(line, "comment", text) for line, text in file.comments if MARKER.search(text)]


def found(file: Parsed) -> list[tuple[int, str, str]]:
    """(line, kind, text) of every suppression comment and every `cast` call in one parsed file."""
    out = marked(file)
    if "cast" not in file.source:
        return out
    for node in ast.walk(file.tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id == "cast") or (isinstance(fn, ast.Attribute) and fn.attr == "cast"):
                out.append((node.lineno, "cast", "cast(...)"))
    return out


def parse(source: str) -> Parsed:
    return Parsed(source, ast.parse(source), comments_of(source))


def counted(parsed: dict[Path, Parsed]) -> Ledger:
    return tally([(rel(p), kind) for p, file in parsed.items()
                  for _, kind, _ in found(file)])


def unnamed(file: Parsed) -> list[int]:
    """Lines whose suppression comment does not name a rule and a reason."""
    return [line for line, _, text in marked(file) if not NAMED.search(text)]


def test_the_gate_sees_the_code(python_tree: dict[Path, Parsed]) -> None:
    assert len(python_tree) > 10, "the gate would pass on almost nothing"


def test_the_held_ledger_is_what_the_code_is(python_tree: dict[Path, Parsed]) -> None:
    wrong = problems(counted(python_tree), load(HELD), FIX, WRITE)
    assert not wrong, "\n".join(wrong)


def test_every_suppression_names_its_rule_and_a_reason(python_tree: dict[Path, Parsed]) -> None:
    bad = {rel(p): unnamed(file) for p, file in python_tree.items()}
    assert not {f: lines for f, lines in bad.items() if lines}


def test_this_test_can_fail() -> None:
    source = (
        "x = f()  # pyright: ignore[reportFoo] - because\n"
        "y = g()  # pyright: ignore\n"
        "z = h()  # noqa: E402 - needed\n"
        "w = cast(int, v)\n"
        "u = typing.cast(int, v)\n"
        "s = '# noqa inside a string is not a comment'\n"
    )
    assert [(line, kind) for line, kind, _ in found(parse(source))] == [
        (1, "comment"), (2, "comment"), (3, "comment"), (4, "cast"), (5, "cast")]
    assert unnamed(parse(source)) == [2]
    held: Ledger = {"a.py": {"comment": 2}}
    assert problems(held, held, "", "") == []
    assert problems({"a.py": {"comment": 3}}, held, "new", "")[0].endswith("new")
    assert "stale" in problems({"a.py": {"comment": 1}}, held, "", "")[0]
    assert total(tally([("a.py", "cast")])) == 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        ledger = counted(parse_tree())
        HELD.write_text(dump(ledger))
        print(f"wrote {HELD.relative_to(ROOT)}: {total(ledger)} suppressions held")
