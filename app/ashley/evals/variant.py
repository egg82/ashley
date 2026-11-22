"""A prompt variant: what to leave out of her turn's prompt, as data, so a candidate cut is measured in the pod on the
code main runs (`--variant PATH` of `python -m ashley.evals house` and `prompt-sizes`). The JSON is one object:

    {"name": "no-presidents", "sections": ["persona.examples"], "examples": ["presidents"],
     "tools": ["reminders_list"], "sources": ["mail"]}

`name` is required; each list is optional and holds names the code already has: `sections` the stable-prompt parts
`prompt-sizes` reports (`persona.<section id>`, `kind`, `tools`, `profile`, `standing`), `examples` the persona's example
ids (`ashley.persona.sections`), `tools` tool names and `sources` the tool sources' keys as `prompt-sizes` groups them.
A key or a name the code does not have is an error that names it. Section and example names are checked here; a tool or
source can only be checked against what a turn offers, so `finish` fails the run naming any the turns never met.
`core`, when present, names the tool sources a turn offers from its first step, the rest loading on demand with
`use_tools` (`ashley.channels.on_demand`): `{"name": "core-a", "core": ["everyday", "reminders"]}`. An empty list offers
the loader alone; `"core": "all"` offers every source; no `core` leaves the turn on the deployed default
(`ashley.channels.on_demand.core_for`). Its names are checked as `sources` are.
`install` makes the variant the one every turn of the process applies (`ashley.channels.cut`)."""

import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from ..channels import cut
from ..persona import prose, sections

FIELDS = ("name", "sections", "examples", "tools", "sources", "core")
OTHER_PARTS = ("kind", "tools", "profile", "standing")
STDIN = "-"
_OBJECT = TypeAdapter(dict[str, object])
_NAMES = TypeAdapter(list[str])


@dataclass(frozen=True)
class Variant:
    """`name` and `digest` (the first 8 hex digits of the sha256 of the JSON, keys sorted) label a report; two runs
    with the same label cut the same."""

    name: str
    digest: str
    cut: cut.Cut

    @property
    def label(self) -> str:
        return f"{self.name}@{self.digest}"


def label(variant: Variant | None) -> str:
    """The report's name for a run: the variant's `label`, or `none`."""
    return "none" if variant is None else variant.label


def _persona_texts() -> list[str]:
    texts = [prose.read(v, sections.FILE) for v in prose.variants()]
    return [t for t in texts if t is not None]


def known_sections() -> frozenset[str]:
    """The stable-prompt part names a variant may cut, across the persona files that ship."""
    ids = {s.id for t in _persona_texts() for s in sections.parse(t)}
    return frozenset({f"persona.{i}" for i in ids} | set(OTHER_PARTS))


def known_examples() -> frozenset[str]:
    return frozenset(i for t in _persona_texts() for i in sections.example_ids(t))


def _names(data: dict[str, object], key: str, known: frozenset[str] | None) -> frozenset[str]:
    try:
        listed = _NAMES.validate_python(data.get(key, []))
    except ValidationError as e:
        raise ValueError(f"variant {key!r} is a list of names") from e
    if not all(listed):
        raise ValueError(f"variant {key!r} is a list of names")
    names = frozenset(listed)
    if known is not None and names - known:
        raise ValueError(f"variant {key!r} names {', '.join(sorted(names - known))}, which the prompt does not have; "
                         f"it has {', '.join(sorted(known))}")
    return names


def _core(data: dict[str, object]) -> frozenset[str] | Literal["all"]:
    return cut.ALL if data["core"] == cut.ALL else _names(data, "core", None)


def parse(text: str) -> Variant:
    """The variant `text` describes. Raises ValueError for text that is not JSON, a key not in `FIELDS`, a missing
    `name`, a name that is not a string, and any section or example the code does not have."""
    try:
        data = _OBJECT.validate_python(json.loads(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"the variant is not JSON: {e.msg}") from e
    except ValidationError as e:
        raise ValueError("a variant is one JSON object") from e
    stray = sorted(set(data) - set(FIELDS))
    if stray:
        raise ValueError(f"variant has no key {', '.join(map(repr, stray))}; its keys are {', '.join(FIELDS)}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("a variant has a `name`")
    shape = cut.Cut(_names(data, "sections", known_sections()), _names(data, "examples", known_examples()),
                    _names(data, "tools", None), _names(data, "sources", None),
                    _core(data) if "core" in data else None)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return Variant(name.strip(), hashlib.sha256(canonical.encode()).hexdigest()[:8], shape)


def read(path: str) -> Variant:
    """`parse` of the file at `path`, or of stdin for `-`. Raises ValueError as `parse` does, and for an unreadable file."""
    try:
        text = sys.stdin.read() if path == STDIN else open(path, encoding="utf-8").read()
    except OSError as e:
        raise ValueError(f"the variant cannot be read: {type(e).__name__}") from e
    return parse(text)


def install(variant: Variant | None) -> None:
    """Make `variant` the cut every turn applies; none, no cut."""
    cut.install(cut.NO_CUT if variant is None else variant.cut)


def finish() -> None:
    """Raises ValueError naming the tools and sources of the installed variant that no turn's catalogue held."""
    unmet = cut.unmet()
    if unmet:
        raise ValueError(f"the variant names {', '.join(unmet)}, which no turn offered: a typo, or a part the run never "
                         "reached; its numbers are the baseline's for them")
