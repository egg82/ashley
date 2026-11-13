"""The Python source the structural gates read, parsed once. `conftest.py` builds each tree a gate reads in a lazy
session fixture, which the time gate does not charge, so a gate's CPU does not grow with the codebase and a worker
parses only what its gates need; a gate's `--write` mode calls `parse_tree` itself."""

import ast
import io
import tokenize
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT.parent / "bridge" / "herdr"
KEEPER = ROOT.parent / "deploy" / "mail-bridge"
SRC = [ROOT / "ashley", ROOT / "tools", ROOT / "tests", BRIDGE, KEEPER]


def rel(p: Path) -> str:
    """A source file's path as the ledgers key it: relative to `app/`, or to the repo for the bridge and the keeper beside it."""
    return p.relative_to(ROOT.parent if BRIDGE in p.parents or KEEPER in p.parents else ROOT).as_posix()


class Parsed(NamedTuple):
    source: str
    tree: ast.Module
    comments: list[tuple[int, str]]  # (line, text) of every comment token


def comments_of(source: str) -> list[tuple[int, str]]:
    return [
        (tok.start[0], tok.string)
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT
    ]


def parse_tree(dirs: Sequence[Path] = SRC) -> dict[Path, Parsed]:
    """Every .py file under `dirs` (all of SRC by default), by path, in sorted order."""
    out: dict[Path, Parsed] = {}
    for p in sorted(p for d in dirs for p in d.rglob("*.py")):
        source = p.read_text(encoding="utf-8")
        out[p] = Parsed(source, ast.parse(source), comments_of(source))
    return out
