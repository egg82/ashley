"""A tool's answer as the items of a watch (`decisions.md`, "Watches wake her when what a read returns changes, until a
condition or a time"): the hash of the whole result, or one item per entry of the list at the spec's `path`, keyed by the
entry's first tracked field and holding its tracked fields."""

import hashlib
import json
from collections.abc import Mapping

from ..criteria.predicates import as_list, as_map
from .config import CONFIG
from .diff import Items, to_items
from .model import ReadFailed
from .tool_target import HASH, WHOLE, ReadSpec


def items_of(text: str, spec: ReadSpec) -> Items | ReadFailed:
    """`bad_result` for a path the answer does not follow, an entry that is not an object, or text that is not JSON where
    a list is wanted; `too_many_items` past `max_items`. Entries that share an identity are told apart by order
    (`id`, `id#2`, ...)."""
    parsed = _json(text)
    if spec.path is None:
        shown = text if parsed is _NOT_JSON else json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        return {WHOLE: {HASH: hashlib.sha256(shown.encode()).hexdigest()[:16]}}
    found = parsed
    for key in spec.path:
        found = (as_map(found) or {}).get(key)
    listed = as_list(found)
    entries = None if listed is None else [as_map(e) for e in listed]
    if entries is None or any(e is None for e in entries):
        return ReadFailed("bad_result")
    if len(entries) > CONFIG.max_items:
        return ReadFailed("too_many_items")
    named: dict[str, Mapping[str, object]] = {}
    for entry in entries:
        fields = {f: _scalar((entry or {}).get(f)) for f in spec.track}
        identity = _text(fields[spec.track[0]])[:CONFIG.max_value_chars]
        key, n = identity, 1
        while key in named:
            n += 1
            key = f"{identity}#{n}"
        named[key] = fields
    try:
        return to_items(named, CONFIG.max_value_chars)
    except ValueError:
        return ReadFailed("bad_result")


_NOT_JSON = object()


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _NOT_JSON


def _scalar(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)
