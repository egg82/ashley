"""What the skills allow, as data (`skills.json`, beside this module): the shape of a kind of work's name (a slug of
`slug_pattern`, at most `max_slug_chars`) and its label (at most `max_label_chars`), the longest skill body, the longest
`what` or `why` of an edit, and how many changelog entries a read carries. Which kinds of work exist is not here: a
kind is a household's row, started by her or the person (`skills.Skills.add_kind`), plus any a seed document names."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("skills.json")
_KEYS = {"slug_pattern", "max_slug_chars", "max_label_chars", "max_body_chars", "max_note_chars", "changelog_read"}


@dataclass(frozen=True)
class SkillsConfig:
    slug_pattern: re.Pattern[str]
    max_slug_chars: int
    max_label_chars: int
    max_body_chars: int
    max_note_chars: int
    changelog_read: int

    def slug_ok(self, kind: str) -> bool:
        return len(kind) <= self.max_slug_chars and self.slug_pattern.fullmatch(kind) is not None

    def label_ok(self, label: str) -> bool:
        return bool(label.strip()) and len(label) <= self.max_label_chars and "\x00" not in label


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _object(raw: object) -> dict[str, object]:
    """`raw` as a JSON object; empty when it is not one."""
    loose: Any = raw
    return {str(k): v for k, v in dict[object, object](loose).items()} if isinstance(raw, dict) else {}


def config_from(raw: object) -> SkillsConfig:
    """The config in parsed `skills.json`. Raises ValueError for any shape but the module docstring's."""
    top = _object(raw)
    if set(top) != _KEYS:
        raise ValueError(f"skills.json has exactly {sorted(_KEYS)}")
    pattern = top["slug_pattern"]
    counts = {n: top[n] for n in _KEYS - {"slug_pattern"}}
    if not isinstance(pattern, str) or not all(_count(c) for c in counts.values()):
        raise ValueError("skills.json has a slug_pattern and limits that are integers of at least 1")
    return SkillsConfig(re.compile(pattern), int(str(counts["max_slug_chars"])), int(str(counts["max_label_chars"])),
                        int(str(counts["max_body_chars"])), int(str(counts["max_note_chars"])),
                        int(str(counts["changelog_read"])))


def load() -> SkillsConfig:
    return config_from(json.loads(FILE.read_text()))
