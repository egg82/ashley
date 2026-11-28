"""The kinds of action a person may let her just do or have her offer first, as data in `kinds.json` beside this module
(`decisions.md`, "What she may just do is a person's setting over the floor"). Each kind has a `label` to show and the
`calls` it covers: a tool, and when `argument` is given, only a call that gives it (one of `values`, compared in lower
case, when they are listed). A call belongs to the first kind that covers it. A kind's `default` is what it is for a person
who has stored nothing for it: `act` unless the kind says `offer`, which a kind whose changes cannot be taken back says.
A kind with a `floor` is one the code always offers first whatever is set: `asks`, its tools' tier holds them in every turn
(`tools/tiers.json`, `ToolSpec.tier`); `irreversible`, `home_assistant/irreversible.json` covers every change it names. A
test holds each `floor` to the code."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FILE = Path(__file__).with_name("kinds.json")
Value = Literal["act", "offer"]
Floor = Literal["asks", "irreversible"]
DEFAULT: Value = "act"
"""What a kind with no floor and no `default` of its own is when its person has set nothing."""
_VALUES: tuple[Value, ...] = ("act", "offer")
_FLOORS: tuple[Floor, ...] = ("asks", "irreversible")


@dataclass(frozen=True)
class Covered:
    """A call to `tool`; with `argument`, only one that gives it, and with `values`, one naming one of them."""

    tool: str
    argument: str | None = None
    values: tuple[str, ...] = ()

    def covers(self, tool: str, arguments: Mapping[str, object]) -> bool:
        if tool != self.tool:
            return False
        if self.argument is None:
            return True
        given = arguments.get(self.argument)
        if given is None or given == "":
            return False
        return not self.values or (isinstance(given, str) and given.lower() in self.values)


@dataclass(frozen=True)
class Kind:
    kind: str
    label: str
    calls: tuple[Covered, ...]
    floor: Floor | None = None
    default: Value = DEFAULT


class TrustRefused(Exception):
    """A choice that is not one a person may store: `unknown_kind`, no such kind; `locked`, `act` for a kind the code
    always offers first. `kind` is the one it concerns."""

    def __init__(self, kind: str, reason: Literal["unknown_kind", "locked"]) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason: Literal["unknown_kind", "locked"] = reason


@dataclass(frozen=True)
class Kinds:
    kinds: tuple[Kind, ...]

    def of(self, tool: str, arguments: Mapping[str, object]) -> Kind | None:
        """The first kind that covers a call to `tool` with `arguments`; None when none does."""
        return next((k for k in self.kinds if any(c.covers(tool, arguments) for c in k.calls)), None)

    def effective(self, stored: Mapping[str, Value]) -> dict[str, Value]:
        """Each kind's value for a person who stored `stored`: `offer` for a kind with a floor whatever they stored,
        else theirs, else the kind's `default`."""
        return {k.kind: "offer" if k.floor is not None else stored.get(k.kind, k.default) for k in self.kinds}

    def checked(self, chosen: Mapping[str, Value]) -> dict[str, Value]:
        """What to store for a person's whole choice `chosen`: only what differs from what the kind is unset, so a
        choice set back to it deletes the row. Raises TrustRefused for a kind that is not one, or `act` on a kind with
        a floor."""
        by_name = {k.kind: k for k in self.kinds}
        kept: dict[str, Value] = {}
        for name, value in chosen.items():
            kind = by_name.get(name)
            if kind is None:
                raise TrustRefused(name, "unknown_kind")
            if kind.floor is not None:
                if value != "offer":
                    raise TrustRefused(name, "locked")
                continue
            if value != kind.default:
                kept[name] = value
        return kept


def load() -> Kinds:
    """The kinds shipped in `kinds.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(raw: object) -> Kinds:
    """Kinds from JSON already parsed. Raises ValueError unless it is `{"kinds": [...]}` of distinct, non-empty kinds,
    each with a label, at least one call, a floor of `asks` or `irreversible` when it has one, and a default of `act` or
    `offer` only when it has no floor."""
    top = _obj(raw)
    if top is None or set(top) != {"kinds"}:
        raise ValueError("kinds.json is {\"kinds\": [...]}")
    kinds = tuple(_kind(k) for k in _listed(top["kinds"]))
    names = [k.kind for k in kinds]
    if not kinds or len(set(names)) != len(names):
        raise ValueError("kinds are listed, each once")
    return Kinds(kinds)


def _obj(value: object) -> dict[str, object] | None:
    loose: Any = value
    return {str(k): v for k, v in dict[object, object](loose).items()} if isinstance(value, dict) else None


def _listed(value: object) -> list[object]:
    loose: Any = value
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return list[object](loose)


def _kind(raw: object) -> Kind:
    got = _obj(raw)
    allowed = {"kind", "label", "calls", "floor", "default"}
    if got is None or set(got) - allowed or not {"kind", "label", "calls"} <= set(got):
        raise ValueError("a kind has kind, label, calls and optionally floor or default")
    kind, label, floor, default = got["kind"], got["label"], got.get("floor"), got.get("default", DEFAULT)
    if not isinstance(kind, str) or not kind or not isinstance(label, str) or not label:
        raise ValueError("a kind names itself and its label")
    calls = tuple(_covered(c) for c in _listed(got["calls"]))
    if not calls:
        raise ValueError(f"{kind} covers at least one call")
    named: Floor | None = next((f for f in _FLOORS if f == floor), None)
    if floor is not None and named is None:
        raise ValueError(f"{kind}'s floor is asks or irreversible")
    unset: Value | None = next((v for v in _VALUES if v == default), None)
    if unset is None or (floor is not None and "default" in got):
        raise ValueError(f"{kind}'s default is act or offer, on a kind with no floor")
    return Kind(kind, label, calls, named, unset)


def _covered(raw: object) -> Covered:
    got = _obj(raw)
    if got is None or set(got) - {"tool", "argument", "values"} or "tool" not in got:
        raise ValueError("a call has tool and optionally argument and values")
    tool, argument = got["tool"], got.get("argument")
    values = _listed(got.get("values", []))
    if not isinstance(tool, str) or not tool or (argument is not None and (not isinstance(argument, str) or not argument)):
        raise ValueError("a call names a tool, and an argument when it gives one")
    texts = tuple(v.lower() for v in values if isinstance(v, str) and v)
    if len(texts) != len(values) or (texts and argument is None):
        raise ValueError("a call's values are non-empty strings of the argument it names")
    return Covered(tool, argument if isinstance(argument, str) else None, texts)
