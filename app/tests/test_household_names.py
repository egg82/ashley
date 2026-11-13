"""No file in the repository names the household that runs it: its people, pet, network, towns, ISPs or hosts. The
names are never in the tree, in any form: CI supplies them in `ASHLEY_HOUSEHOLD_NAMES` (one per line or comma-separated,
a CI secret), and without it the scan skips. Every word, every dotted or hyphenated compound (`host.example.home`,
`10.0.0.1`, `ws-name01`) and every pair of adjacent words of each tracked text file is looked up, lower-cased.

A file may keep a name only under `KEPT`, a held ledger of per-file counts that may only shrink: today the Kubernetes
label prefix, which live manifests select on, and the preferred failback site, which names the deployment's own
Patroni member. `.gitlab-ci.yml` is the private deployment's pipeline and is not published, so it is not scanned."""

import os
import re
import subprocess
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import pytest

pytestmark = pytest.mark.reads_docs  # run on a docs-only pull request (ci.yml)

ROOT = Path(__file__).resolve().parent.parent.parent
NOT_SCANNED = frozenset({".gitlab-ci.yml"})
CANARY = "zq-household-canary"  # always held, so the scan is proven able to find a name
COMPOUND = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)+")
WORD = re.compile(r"[a-z0-9]+")

# Per-file counts of held names a file may still carry; may only go down.
KEPT: dict[str, int] = {
    "app/ashley/referee/failback.json": 1,
    "app/ashley/runs/labels.py": 1,
    "app/tests/bench_look_blind/test_bl_images.py": 1,
    "app/tests/runs_pod_specs_main.json": 2,
    "app/tests/sandbox_support.py": 1,
    "app/tests/test_household_names.py": 1,
    "app/tests/test_looks_kubernetes.py": 2,
    "app/tests/test_looks_warm_looker.py": 2,
    "app/tests/test_runs_pod_log.py": 1,
    "app/tests/warm_look_blind/test_wl_keeper.py": 1,
    "app/tests/warm_look_blind/test_wl_spec.py": 2,
    "docs/decisions/bench-files.md": 2,
    "docs/decisions/mail.md": 1,
    "docs/decisions/tools.md": 1,
}


def held() -> frozenset[str]:
    """The names CI supplies, lower-cased, plus the canary; just the canary when none are supplied."""
    given = re.split(r"[\n,]", os.environ.get("ASHLEY_HOUSEHOLD_NAMES", ""))
    return frozenset({n.strip().lower() for n in given if n.strip()} | {CANARY})


def tokens(text: str) -> Iterable[str]:
    lowered = text.lower()
    words = WORD.findall(lowered)
    yield from words
    yield from COMPOUND.findall(lowered)
    yield from (f"{a} {b}" for a, b in zip(words, words[1:]))


def hits(text: str, names: frozenset[str]) -> int:
    return sum(1 for t in tokens(text) if t in names)


SKIPPED_DIRS = frozenset({".git", "node_modules", "build", "dist", "__pycache__", ".venv", ".pytest_cache",
                          ".hypothesis"})


def tracked() -> list[Path]:
    """The tracked files, by `git ls-files`; where CI's image has no git, every file outside `SKIPPED_DIRS`."""
    try:
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return walked()
    return [ROOT / p for p in listed.decode().split("\0") if p and p not in NOT_SCANNED]


def walked() -> list[Path]:
    found: list[Path] = []
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        found += [Path(directory) / f for f in files if f != ".git"]
    return [p for p in found if str(p.relative_to(ROOT)) not in NOT_SCANNED]


@pytest.fixture(scope="module")
def found() -> tuple[int, Counter[str]]:
    names = held()
    if names == frozenset({CANARY}):
        pytest.skip("ASHLEY_HOUSEHOLD_NAMES is unset: CI supplies the household's names as a secret")
    counts: Counter[str] = Counter()
    scanned = 0
    for path in tracked():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        scanned += 1
        n = hits(text, names)
        if n:
            counts[str(path.relative_to(ROOT))] = n
    return scanned, counts


def test_no_file_names_the_household(found: tuple[int, Counter[str]]) -> None:
    scanned, counts = found
    assert scanned > 1000, f"scanned only {scanned} files"
    over = {p: n for p, n in counts.items() if n > KEPT.get(p, 0)}
    assert over == {}, "a household name (people, pet, network, town, host): move it to settings or reword it"


def test_the_kept_ledger_equals_the_tree(found: tuple[int, Counter[str]]) -> None:
    _, counts = found
    stale = {p: (n, counts.get(p, 0)) for p, n in KEPT.items() if counts.get(p, 0) < n}
    assert stale == {}, "stale: lower or remove these KEPT entries (held, found)"


def test_the_scan_finds_a_held_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASHLEY_HOUSEHOLD_NAMES", "Robin Doe, ws-robin01\nexample.home")
    names = held()
    assert names == frozenset({"robin doe", "ws-robin01", "example.home", CANARY})
    assert hits(f"see {CANARY} and Robin Doe on ws-robin01 at example.home", names) == 4
    assert hits("a household of Toby and Sam at ha.test", names) == 0
