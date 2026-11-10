"""Seed documents: the method a kind of work starts with, before anyone edits it. One markdown file per kind in a
directory (`seeds/` beside this module by default), named `<kind>.md`, opening with a front-matter block of exactly
three lines between `---` lines:

    ---
    kind: code
    label: Code
    seeded_from: agentic-engineering
    ---
    <the document>

`kind` is a slug (`SkillsConfig.slug_ok`), `label` what a screen calls it, `seeded_from` the skill of Alana's it was
adapted from. A seed also makes its kind exist for every household. A household's first edit of a kind replaces the seed
for that household; an unedited kind reads whatever seed ships now."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .config import SkillsConfig

DIRECTORY = Path(__file__).with_name("seeds")


@dataclass(frozen=True)
class Seed:
    kind: str
    label: str
    seeded_from: str
    body: str


def parse(text: str, config: SkillsConfig, name: str) -> Seed:
    """The seed in one file's `text`. Raises ValueError, naming the file, for a missing or extra front-matter line, a
    kind that is not a slug or not the file's name, a bad label, an empty `seeded_from`, or an empty or too long body."""
    lines = text.split("\n")
    if len(lines) < 6 or lines[0] != "---" or lines[4] != "---":
        raise ValueError(f"seed {name}: starts with a --- block of kind, label and seeded_from")
    fields: dict[str, str] = {}
    for line in lines[1:4]:
        key, sep, value = line.partition(": ")
        if not sep or key in fields:
            raise ValueError(f"seed {name}: front matter is kind, label, seeded_from, each as `key: value`")
        fields[key] = value.strip()
    if list(fields) != ["kind", "label", "seeded_from"]:
        raise ValueError(f"seed {name}: front matter is kind, label, seeded_from, each as `key: value`")
    kind, label, source, body = fields["kind"], fields["label"], fields["seeded_from"], "\n".join(lines[5:]).strip()
    if not config.slug_ok(kind) or f"{kind}.md" != name or not config.label_ok(label):
        raise ValueError(f"seed {name}: kind is a slug and the file's name, label is a short name")
    if not source:
        raise ValueError(f"seed {name}: seeded_from names the skill it was adapted from")
    if not body or len(body) > config.max_body_chars:
        raise ValueError(f"seed {name}: a body of 1 to {config.max_body_chars} characters")
    return Seed(kind, label, source, body)


def load(config: SkillsConfig, directory: Path = DIRECTORY) -> Mapping[str, Seed]:
    """Every seed in `directory` by kind; none when it is absent. Raises ValueError for any file `parse` refuses, or a
    file that is not `<kind>.md`."""
    found: dict[str, Seed] = {}
    for path in sorted(directory.glob("*")) if directory.is_dir() else []:
        if path.name.startswith("."):
            continue
        seed = parse(path.read_text(), config, path.name)
        found[seed.kind] = seed
    return MappingProxyType(found)
