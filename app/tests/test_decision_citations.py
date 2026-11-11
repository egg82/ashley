"""Every place that cites a decision by title names something that exists, and the decisions index is true.

A citation is the quoted string right after a mention of `decisions.md` (`decisions.md`, "Title" or `decisions.md`
("Title"), the quote may wrap to the next comment line) or after `(decisions, `. It resolves when it is exactly an
entry of the index, `docs/decisions.md`, or when it is the start of exactly one `##` or `###` heading or bold lead in
`docs/decisions/`: citations name a part inside a decision, or shorten a long title. A trailing "..." is dropped.

The index is true when each entry's file has a `## ` heading with the entry's exact title, and every `## ` heading in
`docs/decisions/` has an entry pointing at its file."""

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
INDEX = REPO / "docs" / "decisions.md"
DECISIONS = REPO / "docs" / "decisions"
SUFFIXES = frozenset({".py", ".ts", ".tsx", ".md", ".json"})
SKIPPED_DIRS = frozenset({".git", "node_modules", "build", "dist", "__pycache__", ".venv", "venv", ".pytest_cache",
                          ".hypothesis"})
CITE = re.compile(
    r"(?:\bdecisions\.md`?(?:,|[ \t]|(?=\n))|\(decisions,)[ \t]*"
    r"(?:\n[ \t]*(?:#+|//|\*|>)?[ \t]*)?\(?\"([^\"]{1,300}?)\""
)
CONTINUATION = re.compile(r"\s*\n[ \t]*(?:#+|//|\*|>)?[ \t]*")
ENTRY = re.compile(r"(?m)^- \[(.+?)\]\((decisions/[\w\-]+\.md)\): \S")
HEADING = re.compile(r"(?m)^(##|###) (.+)$")
BOLD_LEAD = re.compile(r"(?m)^[ \t]*(?:- )?\*\*([^*]+?)\*\*")
FLOOR = 180


def cited(text: str) -> list[tuple[int, str]]:
    """(line, title) for each citation in a file's text."""
    return [(text.count("\n", 0, m.start()) + 1, CONTINUATION.sub(" ", m.group(1)).strip()) for m in CITE.finditer(text)]


def sources(root: Path) -> list[Path]:
    """The files citations are read from; this file plants citations of its own, so it is left out."""
    found: list[Path] = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        found += [Path(directory) / f for f in files if Path(f).suffix in SUFFIXES]
    return [p for p in found if p != Path(__file__).resolve()]


def entries(index: str) -> dict[str, str]:
    """Index title -> its file, relative to `docs/`."""
    return {title: path for title, path in ENTRY.findall(index)}


def targets(files: dict[str, str]) -> list[str]:
    """Every `##`/`###` heading and bold lead in the decision files, whitespace collapsed."""
    found: list[str] = []
    for text in files.values():
        found += [title for _, title in HEADING.findall(text)]
        found += [" ".join(lead.split()).rstrip(".:") for lead in BOLD_LEAD.findall(text)]
    return found


def resolves(title: str, index: dict[str, str], known: list[str]) -> bool:
    title = re.sub(r"(\.\.\.|…)$", "", title).strip()
    if title in index:
        return True
    hits = [t for t in known if t == title or (t.startswith(title) and not t[len(title)].isalnum())]
    return len(hits) == 1


def unresolved(root: Path, index: dict[str, str], known: list[str]) -> tuple[int, list[str]]:
    """(how many citations were read, the ones that resolve to nothing or to several)."""
    seen = 0
    wrong: list[str] = []
    for path in sources(root):
        for line, title in cited(path.read_text(encoding="utf-8", errors="replace")):
            seen += 1
            if not resolves(title, index, known):
                wrong.append(f"{path.relative_to(root)}:{line}: \"{title}\" is no decision, heading or bold lead")
    return seen, wrong


def index_problems(index: dict[str, str], files: dict[str, str]) -> list[str]:
    wrong: list[str] = []
    for title, path in index.items():
        if path not in files:
            wrong.append(f"index entry \"{title}\" points at {path}, which does not exist")
        elif f"\n## {title}\n" not in "\n" + files[path]:
            wrong.append(f"index entry \"{title}\": {path} has no `## {title}` heading")
    for path, text in files.items():
        for level, title in HEADING.findall(text):
            if level == "##" and index.get(title) != path:
                wrong.append(f"{path}: `## {title}` has no index entry pointing at it")
    return wrong


def decision_files() -> dict[str, str]:
    return {f"decisions/{p.name}": p.read_text(encoding="utf-8") for p in sorted(DECISIONS.glob("*.md"))}


def test_every_cited_decision_resolves() -> None:
    files = decision_files()
    seen, wrong = unresolved(REPO, entries(INDEX.read_text(encoding="utf-8")), targets(files))
    assert seen >= FLOOR, f"read {seen} citations, expected at least {FLOOR}: the finder sees too little"
    assert not wrong, "\n".join(wrong)


def test_the_index_matches_the_decision_files() -> None:
    files = decision_files()
    index = entries(INDEX.read_text(encoding="utf-8"))
    assert len(files) >= 10 and len(index) >= 50, f"read {len(files)} files and {len(index)} entries: too few"
    assert not index_problems(index, files), "\n".join(index_problems(index, files))


def test_the_gate_sees_planted_citations_and_fails_on_unknown_ones(tmp_path: Path) -> None:
    files = {"decisions/a.md": "# A\n\n## Real title, long\n\n- **A bold lead, wrapped\n  across lines.** Body.\n"}
    index = entries("- [Real title, long](decisions/a.md): one line.\n")
    known = targets(files)
    (tmp_path / "good.py").write_text(
        '"""As `decisions.md`, "Real title, long" says, and `docs/decisions.md` ("Real title").\n'
        '(decisions, "A bold lead, wrapped across lines") and `decisions.md`,\n'
        '# "A bold lead"."""\n{"docs/decisions.md": 4}\n'
    )
    assert unresolved(tmp_path, index, known) == (4, [])
    (tmp_path / "bad.md").write_text('See `decisions.md`, "A title nobody wrote".\n')
    seen, wrong = unresolved(tmp_path, index, known)
    assert seen == 5 and len(wrong) == 1 and wrong[0].startswith("bad.md:1:")
    assert index_problems(index, files) == []
    assert len(index_problems(index, {"decisions/a.md": files["decisions/a.md"] + "\n## Unlisted\n"})) == 1
    assert len(index_problems(entries("- [Gone](decisions/a.md): x.\n"), files)) == 2
