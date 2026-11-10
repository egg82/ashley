"""`docs/systems.md` is the inventory an agent checks before building something, so what it cites must exist. Every
backticked repo path must be a file or directory, and every `ashley.module.symbol` must import and resolve.

Conventions inside the backticks, which are the only things this reads (prose is never checked):
- `planned:<path>` or `planned:<ashley.module.symbol>`: a reference to something not built yet. Skipped while the
  target is missing and FAILS once it exists, so the marker is dropped and the reference is checked from then on.
- `<repo>:<path>`, e.g. `kubernetes:kustomization/etcd`: a path in another repo, not checked here.
- a path beginning `~` is on a workstation, not checked."""

import importlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SYSTEMS = REPO / "docs" / "systems.md"
SPAN = re.compile(r"`([^`\n]+)`")
PATHLIKE = re.compile(r"[\w.\-]+(/[\w.\-]+)+/?|[\w\-]+\.(md|py|yaml|yml|json|sh|ts|tsx|mjs)")
SYMBOL = re.compile(r"ashley(\.\w+)+")
EXTERNAL = re.compile(r"[a-z][\w\-]*:(?!//)\S")
FLOOR = 3


def symbol_exists(dotted: str) -> bool:
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj: object = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for name in parts[cut:]:
            if not hasattr(obj, name):
                return False
            obj = getattr(obj, name)
        return True
    return False


def target_exists(token: str, root: Path) -> bool:
    return symbol_exists(token) if SYMBOL.fullmatch(token) else (root / token).exists()


def check(text: str, root: Path = REPO) -> tuple[int, list[str]]:
    """(how many citations were read, what is wrong with them)."""
    seen = 0
    wrong: list[str] = []
    for token in SPAN.findall(text):
        if token.startswith("planned:"):
            target = token.removeprefix("planned:")
            seen += 1
            if target_exists(target, root):
                wrong.append(f"{token}: it exists now, drop `planned:`")
        elif token.startswith("~") or " " in token:
            continue
        elif EXTERNAL.match(token) and not SYMBOL.fullmatch(token) and not PATHLIKE.fullmatch(token):
            seen += 1
        elif SYMBOL.fullmatch(token) or PATHLIKE.fullmatch(token):
            seen += 1
            if not target_exists(token, root):
                wrong.append(f"{token}: not found")
    return seen, wrong


def test_the_citations_in_systems_md_resolve() -> None:
    seen, wrong = check(SYSTEMS.read_text(encoding="utf-8"))
    assert seen >= FLOOR, f"read {seen} citations in {SYSTEMS.name}, expected at least {FLOOR}: the gate sees too little"
    assert not wrong, "\n".join(wrong)


def test_the_gate_fails_on_planted_citations(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_text("x")
    text = (
        "`docs/real.md` `ashley.services.get` `ashley.services` `planned:docs/later.md` "
        "`kubernetes:kustomization/x` `~/elsewhere/y` `two words/here` `plain` `ashley.db.database.Database`"
    )
    assert check(text, tmp_path) == (6, [])
    seen, wrong = check("`docs/missing.md` `ashley.services.nope` `ashley.nomodule.thing` `planned:docs/real.md`", tmp_path)
    assert seen == 4 and len(wrong) == 4
    assert wrong[0].startswith("docs/missing.md") and wrong[3].startswith("planned:docs/real.md")
