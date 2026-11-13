"""The shipped persona's sections, and which of them a household may override (`ashley.skills.persona`).

`ashley.md` is cut into sections by marker lines, each a whole line of exactly this shape:

    <!-- section id=<id> override=<allowed|locked> label="<label>" -->

`id` is a slug (`^[a-z][a-z0-9-]*$`), unique in the file, and is what an override is keyed by. `override` is the
explicit field that decides the lock: `allowed` is taste (her register, her wit, her examples) a household may replace
from the web; `locked` is everything else, the output contract code depends on (the reply's fields and their rules)
and the rules that hold whatever anyone asks. `label` is what a screen calls the section. A section is the text from
its marker to the next marker or the end of the file. A heading belongs to the text before the section it heads, so an
override replaces a section's body and never its heading. Nothing is decided from a heading's or a section's words.

A file with markers starts with one; text before the first marker, a line that opens `<!-- section` and is not of the
shape, a repeated id or a section with no text is refused. A persona file with no marker is one locked section.

Rendering drops the marker lines and joins the sections' stripped bodies with one blank line, so with no overrides the
text is the file as written less its markers, byte for byte. An override applies only to an `allowed` section of the
text being rendered: one for a locked id, or for an id the shipped text no longer has (renamed or removed in a later
release), is ignored, so no stored row of any origin can change a locked section."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from ..inference.model import DEFAULT_VARIANT
from . import prose

Override = Literal["allowed", "locked"]
MARKER_PREFIX = "<!-- section"
FILE = "ashley.md"
_MARKER = re.compile(r'<!-- section id=([a-z][a-z0-9-]*) override=(allowed|locked) label="([^"\x00\s][^"\x00]*)" -->')


@dataclass(frozen=True)
class Section:
    """One section of a persona file: `body` is its shipped text, stripped, without the marker line."""

    id: str
    label: str
    override: Override
    body: str


def parse(text: str) -> tuple[Section, ...]:
    """The sections of a persona file's `text`, in order. Raises ValueError for the shapes the module docstring
    refuses. A file with no marker is one locked section with id `all`."""
    lines = text.strip().split("\n")
    if not any(line.startswith(MARKER_PREFIX) for line in lines):
        return (Section("all", "all", "locked", text.strip()),)
    if not lines[0].startswith(MARKER_PREFIX):
        raise ValueError("a persona file with sections starts with a marker")
    found: list[Section] = []
    for line in lines:
        if not line.startswith(MARKER_PREFIX):
            found[-1] = Section(found[-1].id, found[-1].label, found[-1].override, f"{found[-1].body}\n{line}")
            continue
        found.append(_opened(line, {s.id for s in found}))
    return tuple(_stripped(s) for s in found)


def _opened(line: str, seen: set[str]) -> Section:
    match = _MARKER.fullmatch(line)
    if match is None:
        raise ValueError(f"not a section marker: {line[:80]!r}")
    if match[1] in seen:
        raise ValueError(f"section {match[1]!r} is marked twice")
    override: Override = "allowed" if match[2] == "allowed" else "locked"
    return Section(match[1], match[3].strip(), override, "")


def _stripped(section: Section) -> Section:
    if not section.body.strip():
        raise ValueError(f"section {section.id!r} has no text")
    return Section(section.id, section.label, section.override, section.body.strip())


def render(text: str, overrides: Mapping[str, str]) -> str:
    """`text` with each `allowed` section's body replaced by `overrides[id]` (stripped) when present, marker lines
    dropped, sections joined by one blank line. Overrides for other ids are ignored. Deterministic. Raises ValueError
    as `parse` does."""
    return "\n\n".join(body for _, body in bodies(text, overrides))


def bodies(text: str, overrides: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """`render`'s sections as `(id, body)` pairs in file order, each body as `render` joins it."""
    return tuple((s.id, _body(s, overrides)) for s in parse(text))


def _body(section: Section, overrides: Mapping[str, str]) -> str:
    if section.override == "allowed" and section.id in overrides:
        return overrides[section.id].strip()
    return section.body


def catalogue() -> tuple[Section, ...]:
    """The `allowed` sections of the default variant's `ashley.md`, in file order: what a household may override,
    each with the shipped body a revert returns to."""
    text = prose.read(DEFAULT_VARIANT, FILE)
    if text is None:
        raise ValueError(f"no {FILE} ships")
    return tuple(s for s in parse(text) if s.override == "allowed")
