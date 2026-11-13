"""A measurements piece's body (kind `measurements`, format `measurements`, `decisions.md`, "Measurements are structured
data, each with its source"): one JSON object of exactly `items`, a list of rows, each a number or a choice.

A number (a row with no `kind`) is an object with
- `name`: an identifier (letters, digits, underscore; not starting with a digit), unique within the piece;
- `value`: a finite number;
- `unit`: one of `UNITS`: `mm` (every length is in millimetres), `deg`, `count`, `g` (every mass in grams), `ml` (every
  volume in millilitres) or `min` (every duration in minutes);
- `source`: one of `SOURCES`: `measured` (the person measured, counted or stated it, or a file embodies it),
  `datasheet` (published), `accepted` (the person was asked and said to go with this value), `bound` (a soft or varying
  thing whose true size is anywhere in `value` ± `tolerance`) or `guessed`;
- `tolerance`: optional, a finite ± of at least 0 in the unit; a `bound` row must have one above 0;
- `ref`: optional text of at most `MAX_REF` characters (where a datasheet is, what measured it, the photo piece seen);
- `given`: optional, the name of a choice row in the same piece that this number belongs to (a strap's width is given
  its form).

A choice (`"kind": "choice"`, the only other kind) is what kind of thing something is, in plain words, with
- `name`: as a number's;
- `label`: what it is about, for the person, 1 to `MAX_LABEL` characters;
- `value`: 1 to `MAX_VALUE` characters, and one of `options` when they are given;
- `options`: optional, `MIN_OPTIONS` to `MAX_OPTIONS` distinct values of the same length limit;
- `source`: one of `CHOICE_SOURCES`: `stated` (the person said it), `seen` (in a photo or file piece), `datasheet` (a
  published page or recipe piece), `accepted` (the person said to go with her value) or `guessed`;
- `turn`: optional, the person's turn that says it, and only with `stated` or `accepted`;
- `piece`: optional, the bench piece it comes from, and only with `seen` or `datasheet`;
- `ref`: as a number's.
Whether a citation must be there and names something real is checked where its context is (`cited_pieces`,
`cited_turns`), not here. Every source but `guessed` is confirmed (`confirmed`). Any other key or type is refused. An
empty body is a draft and passes."""

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .automation_config import object_of

MAX_REF = 200
MAX_LABEL = 60
MAX_VALUE = 80
MIN_OPTIONS, MAX_OPTIONS = 2, 6
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
UNITS = frozenset(("mm", "deg", "count", "g", "ml", "min"))
GUESSED = "guessed"
CHOICE = "choice"
SOURCES = frozenset(("measured", "datasheet", "accepted", "bound", GUESSED))
TURN_SOURCES = frozenset(("stated", "accepted"))
PIECE_SOURCES = frozenset(("seen", "datasheet"))
CHOICE_SOURCES = TURN_SOURCES | PIECE_SOURCES | {GUESSED}
_REQUIRED = frozenset(("name", "value", "unit", "source"))
_FIELDS = _REQUIRED | {"tolerance", "ref", "given"}
_CHOICE_REQUIRED = frozenset(("kind", "name", "label", "value", "source"))
_CHOICE_FIELDS = _CHOICE_REQUIRED | {"options", "turn", "piece", "ref"}


@dataclass(frozen=True)
class Measurement:
    name: str
    value: float
    unit: str
    source: str
    tolerance: float | None
    ref: str | None
    given: str | None = None


@dataclass(frozen=True)
class Choice:
    name: str
    label: str
    value: str
    source: str
    options: tuple[str, ...] = ()
    turn: int | None = None
    piece: int | None = None
    ref: str | None = None


Row = Measurement | Choice


def items_of(body: str) -> tuple[Row, ...] | None:
    """The rows `body` holds; None when it is empty or not of the shape above."""
    try:
        loaded = object_of(json.loads(body))
    except ValueError:
        return None
    if loaded is None or set(loaded) != {"items"}:
        return None
    raw: object = loaded["items"]
    listed: Any = raw
    if not isinstance(raw, list):
        return None
    got: list[Row] = []
    for item in listed:
        one = _row(item)
        if one is None:
            return None
        got.append(one)
    choices = {r.name for r in got if isinstance(r, Choice)}
    if any(isinstance(r, Measurement) and r.given is not None and r.given not in choices for r in got):
        return None
    return tuple(got) if len({r.name for r in got}) == len(got) else None


def well_formed(body: str) -> bool:
    """Whether `body` is empty or a list of rows of the shape above."""
    return not body.strip() or items_of(body) is not None


def confirmed(row: Row) -> bool:
    """Whether `row` is confirmed: every source but `guessed` is. The one test of it, read by a check's verdict
    (`model_report`), the guard on her edits (`rewrites_confirmed`) and what a later turn carries (`bench_now`)."""
    return row.source != GUESSED


def shown_value(row: Row) -> str:
    """What the person is shown of `row`, and what a `Surfaced` names it by: a choice's value, a number's value and
    unit (`15 mm`)."""
    return row.value if isinstance(row, Choice) else f"{format(row.value, '.15g')} {row.unit}"


def shown_label(row: Row) -> str:
    """What `row` is about, for the person: a choice's label, a number's name with its underscores read as spaces."""
    return row.label if isinstance(row, Choice) else row.name.replace("_", " ")


def rewrites_confirmed(before: str, after: str) -> bool:
    """Whether `after` changes what a confirmed row of `before` holds (a number's value, unit or tolerance; a choice's
    value) under the same name and kind, while keeping where it came from as it was (a number's source and ref; a
    choice's source, turn and piece). A row removed, renamed, or rewritten together with a new source or citation is not
    counted. False when either body is not of the shape above."""
    old = {m.name: m for m in items_of(before) or () if confirmed(m)}
    for m in items_of(after) or ():
        was = old.get(m.name)
        if was is not None and type(m) is type(was) and _origin(m) == _origin(was) and _held(m) != _held(was):
            return True
    return False


def cited_pieces(before: str, after: str) -> tuple[int | None, ...]:
    """The `piece` of each choice row of `after` whose source cites a piece (`PIECE_SOURCES`) and which is new or
    changed from `before`'s row of that name; None for such a row that names none. A row kept as it was is not judged
    again, so a person's row stays as they left it."""
    return tuple(c.piece for c in _changed_choices(before, after) if c.source in PIECE_SOURCES)


def cited_turns(before: str, after: str) -> tuple[int | None, ...]:
    """As `cited_pieces`, for the `turn` of rows whose source cites a turn (`TURN_SOURCES`)."""
    return tuple(c.turn for c in _changed_choices(before, after) if c.source in TURN_SOURCES)


def _changed_choices(before: str, after: str) -> list[Choice]:
    old = {m.name: m for m in items_of(before) or ()}
    return [m for m in items_of(after) or () if isinstance(m, Choice) and old.get(m.name) != m]


def _origin(row: Row) -> tuple[object, ...]:
    return (row.source, row.ref) if isinstance(row, Measurement) else (row.source, row.turn, row.piece)


def _held(row: Row) -> tuple[object, ...]:
    return (row.value, row.unit, row.tolerance) if isinstance(row, Measurement) else (row.value,)


def _row(item: object) -> Row | None:
    fields = object_of(item)
    if fields is None:
        return None
    return _choice(fields) if "kind" in fields else _one(fields)


def _one(fields: dict[str, Any]) -> Measurement | None:
    if not _REQUIRED <= frozenset(fields) <= _FIELDS:
        return None
    name, unit, source = fields["name"], fields["unit"], fields["source"]
    value, tolerance, ref = _number(fields["value"]), _number(fields.get("tolerance", 0)), fields.get("ref", "")
    given = fields.get("given")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        return None
    if not isinstance(unit, str) or unit not in UNITS or not isinstance(source, str) or source not in SOURCES:
        return None
    if value is None or tolerance is None or tolerance < 0 or (source == "bound" and tolerance <= 0):
        return None
    if not isinstance(ref, str) or len(ref) > MAX_REF:
        return None
    if "given" in fields and (not isinstance(given, str) or not NAME.fullmatch(given)):
        return None
    return Measurement(name, value, unit, source, tolerance if "tolerance" in fields else None,
                       ref if "ref" in fields else None, given)


def _choice(fields: dict[str, Any]) -> Choice | None:
    if fields.get("kind") != CHOICE or not _CHOICE_REQUIRED <= frozenset(fields) <= _CHOICE_FIELDS:
        return None
    name, label, value, source = fields["name"], fields["label"], fields["value"], fields["source"]
    options, ref = _options(fields["options"]) if "options" in fields else (), fields.get("ref", "")
    if not isinstance(name, str) or not NAME.fullmatch(name) or not _words(label, MAX_LABEL) or not _words(value, MAX_VALUE):
        return None
    if options is None or (options and value not in options):
        return None
    if not isinstance(source, str) or source not in CHOICE_SOURCES or not isinstance(ref, str) or len(ref) > MAX_REF:
        return None
    turn, piece = fields.get("turn"), fields.get("piece")
    if not _cites(fields, "turn", TURN_SOURCES) or not _cites(fields, "piece", PIECE_SOURCES):
        return None
    return Choice(name, label, value, source, options, turn, piece, ref if "ref" in fields else None)


def _options(raw: object) -> tuple[str, ...] | None:
    """`raw` as `MIN_OPTIONS` to `MAX_OPTIONS` distinct values; None when it is not that."""
    loose: Any = raw
    listed = list[object](loose) if isinstance(raw, list) else []
    words = tuple(w for w in listed if isinstance(w, str) and _words(w, MAX_VALUE))
    ok = len(words) == len(listed) and MIN_OPTIONS <= len(words) <= MAX_OPTIONS and len(set(words)) == len(words)
    return words if ok else None


def _cites(fields: dict[str, Any], key: str, sources: frozenset[str]) -> bool:
    """Whether the id under `key` is absent, or a positive integer on a row whose source cites that kind of thing."""
    if key not in fields:
        return True
    got = fields[key]
    return type(got) is int and got >= 1 and fields["source"] in sources


def _words(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None
