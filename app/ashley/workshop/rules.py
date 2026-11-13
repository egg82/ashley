"""What a bench allows, as data: the piece kinds (`kinds.json`, a Type Object: a new kind is an entry, never a class)
and the bench's limits (`workshop.json`). Both files sit beside this module.

`kinds.json` maps each kind's name to `{"family", "label", "max_chars", "format"}`, plus `language` for a code kind and
`outside` (a boolean, false when left out) for a kind whose body or page text is written outside the household, and
`by_code` (a boolean, false when left out) for a kind only the bench jobs' runner makes and changes (`model.RUNNER`):
- `family` is `stored`, whose piece body is its content, kept in Postgres; or `live`, whose body is a reference to a
  source the client shows in a frame (`site`, `video`); or `large`, whose body names bytes kept in the object store
  (`image`, `file`; `stored_file`).
- `label` is what a screen calls the kind.
- `max_chars` is the longest body a piece of the kind may have, at least 1.
- `format` is how the body is written: `markdown`, `plain` (text shown as typed), `code` (source, which names its
  `language`; only a code kind has one), `automation` (Home Assistant's automation config as JSON,
  `automation_config`), `wake` (a rule for one wake from the house as JSON, `wake_rule`), `facts` (named values with unit and
  source as JSON, `facts`), `diagram` (Mermaid source, drawn by the client), `site` (one https URL) or
  `video` (a JSON object of a url and a start; both in `embed`), `screen` (a piece of a device's screen drawn by the
  client from its own sources, whose body is empty) or `controls` (a screen's touch buttons as JSON,
  `screen_controls`) or `reader` (a page's text and where it came from as
  JSON, `reader`), `recipe` (a published recipe and the headcount to scale it to as JSON, `recipe`), `job` (a bench job's state as JSON, `job_body`), `image` or `file` (a large piece's body: the hash, size, media type and name of its bytes,
  `stored_file`).
- family `screen` is a piece of a device's screen, not of a bench: `load` leaves those kinds out and `load_screen`
  keeps only them.

`workshop.json` has exactly `max_pieces` (how many pieces one bench holds at most), `title_max_chars` (the longest
title of a bench or a piece), `recent_commands` (how many of the latest commands a bench's read carries) and
`undo_window` (how many of the latest commands, refusals and Undos among them, an Undo reaches back over), each at
least 1. `screen.json` has those four and `required` (the kinds a screen always holds one of, a list of names) and
`one_each` (whether a screen holds at most one piece of a kind), and sets the limits of a device's screen."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, get_args

from .json_shape import list_of, object_of

KINDS_FILE = Path(__file__).with_name("kinds.json")
LIMITS_FILE = Path(__file__).with_name("workshop.json")
SCREEN_FILE = Path(__file__).with_name("screen.json")

Family = Literal["stored", "live", "large", "screen"]
BodyFormat = Literal["markdown", "plain", "code", "automation", "wake", "facts", "diagram", "site", "video", "reader", "recipe", "image", "file", "clip", "audio", "screen", "controls", "job"]


@dataclass(frozen=True)
class Kind:
    """One kind of piece."""

    name: str
    family: Family
    label: str
    max_chars: int
    format: BodyFormat = "markdown"
    language: str | None = None
    outside: bool = False
    by_code: bool = False


@dataclass(frozen=True)
class Rules:
    """Everything `decide` checks a command against besides the bench itself. `kinds` by name. `required` names the
    kinds a layout must keep one piece of (a Remove, Archive or Undo that would leave none is refused); `one_each` makes
    a layout hold at most one piece of a kind."""

    kinds: Mapping[str, Kind]
    max_pieces: int
    title_max_chars: int
    recent_commands: int
    undo_window: int
    required: frozenset[str] = frozenset()
    one_each: bool = False

    def __post_init__(self) -> None:
        if min(self.max_pieces, self.title_max_chars, self.recent_commands, self.undo_window) < 1:
            raise ValueError("workshop limits must each be at least 1")

    def shows_outside(self, kinds: Iterable[str]) -> bool:
        """Whether any of the piece `kinds` is one marked `outside`; a kind these rules do not have counts."""
        return any(k not in self.kinds or self.kinds[k].outside for k in kinds)


def kinds_from(raw: object) -> Mapping[str, Kind]:
    """The kinds in a parsed `kinds.json`. Raises ValueError for a shape outside the module docstring's."""
    top = _object(raw)
    if not top:
        raise ValueError("kinds.json is a non-empty object of kinds")
    return MappingProxyType({name: _kind(name, entry) for name, entry in top.items()})


def _kind(name: str, raw: object) -> Kind:
    entry = _object(raw)
    required = {"family", "label", "max_chars", "format"}
    if not required <= set(entry) <= required | {"language", "outside", "by_code"}:
        raise ValueError(f"kind {name!r} has family, label, max_chars and format, and a language when it is code")
    outside, by_code = entry.get("outside", False), entry.get("by_code", False)
    if not isinstance(outside, bool) or not isinstance(by_code, bool):
        raise ValueError(f"kind {name!r}: outside and by_code are true or false")
    family, label, max_chars, body_format = entry["family"], entry["label"], entry["max_chars"], entry["format"]
    if family not in get_args(Family) or not isinstance(label, str) or not label.strip():
        raise ValueError(f"kind {name!r} needs a family of {get_args(Family)} and a label")
    if not _is_count(max_chars):
        raise ValueError(f"kind {name!r} needs max_chars of at least 1")
    if body_format not in get_args(BodyFormat):
        raise ValueError(f"kind {name!r} needs a format of {get_args(BodyFormat)}")
    language = entry.get("language")
    if (body_format == "code") != (language is not None) or (language is not None and not _is_name(language)):
        raise ValueError(f"kind {name!r}: a code kind has a non-empty language, any other has none")
    return Kind(name, _family(family), label, _int(max_chars), _format(body_format),
                None if language is None else str(language), outside, by_code)


def _family(raw: object) -> Family:
    for known in get_args(Family):
        if raw == known:
            return known
    raise ValueError(f"unknown family {raw!r}")


def _format(raw: object) -> BodyFormat:
    for known in get_args(BodyFormat):
        if raw == known:
            return known
    raise ValueError(f"unknown format {raw!r}")


def rules_from(kinds: object, limits: object) -> Rules:
    """The rules from parsed `kinds.json` and `workshop.json`. Raises ValueError for a shape outside the docstring's."""
    names = {"max_pieces", "title_max_chars", "recent_commands", "undo_window"}
    top = _object(limits)
    if set(top) != names or not all(_is_count(top[n]) for n in names):
        raise ValueError(f"workshop.json has exactly {sorted(names)}, each an integer of at least 1")
    return Rules(_of_family(kinds_from(kinds), screen=False), _int(top["max_pieces"]), _int(top["title_max_chars"]),
                 _int(top["recent_commands"]), _int(top["undo_window"]))


def screen_rules_from(kinds: object, limits: object) -> Rules:
    """The rules of a device's screen from parsed `kinds.json` and `screen.json`. Raises ValueError for a shape outside
    the docstring's, or a `required` kind the screen kinds lack."""
    names = {"max_pieces", "title_max_chars", "recent_commands", "undo_window"}
    top = _object(limits)
    if set(top) != names | {"required", "one_each"} or not all(_is_count(top[n]) for n in names):
        raise ValueError(f"screen.json has exactly {sorted(names)} (each an integer of at least 1), required and one_each")
    required, one_each = top["required"], top["one_each"]
    names_required = list_of(required)
    if names_required is None or not all(isinstance(r, str) for r in names_required) or not isinstance(one_each, bool):
        raise ValueError("screen.json's required is a list of kind names and one_each is true or false")
    held = _of_family(kinds_from(kinds), screen=True)
    needed = frozenset(str(r) for r in names_required)
    if not needed <= set(held):
        raise ValueError("screen.json requires a kind the screen does not have")
    return Rules(held, _int(top["max_pieces"]), _int(top["title_max_chars"]), _int(top["recent_commands"]),
                 _int(top["undo_window"]), needed, one_each)


def _of_family(kinds: Mapping[str, Kind], screen: bool) -> Mapping[str, Kind]:
    return MappingProxyType({n: k for n, k in kinds.items() if (k.family == "screen") == screen})


def _object(data: object) -> dict[str, object]:
    """`data` as a JSON object; empty when it is not one."""
    return object_of(data) or {}


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _int(value: object) -> int:
    loose: Any = value
    return int(loose)


def load() -> Rules:
    """The rules shipped beside this module. Raises ValueError when either file is malformed."""
    return rules_from(json.loads(KINDS_FILE.read_text()), json.loads(LIMITS_FILE.read_text()))


def load_screen() -> Rules:
    """The rules of a device's screen shipped beside this module. Raises ValueError when either file is malformed."""
    return screen_rules_from(json.loads(KINDS_FILE.read_text()), json.loads(SCREEN_FILE.read_text()))
