"""What a `tool` watch reads, kept in the watch's `target` as canonical JSON so one read is one watch: `tool`, its fixed
`arguments`, `track` (1 to 8 field names; the first is an item's identity) and, for a result that holds a list, `path`:
the keys down to that list, empty when the result is the list. Without `path` the whole result is one item, its hash."""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from ..criteria.predicates import as_list, as_map
from .model import MAX_TARGET

WHOLE = "result"
HASH = "hash"
_MAX_PATH = 6


@dataclass(frozen=True)
class ReadSpec:
    tool: str
    arguments: Mapping[str, object]
    track: tuple[str, ...]
    path: tuple[str, ...] | None = None


def target_of(spec: ReadSpec) -> str:
    """The canonical target of `spec`. Raises ValueError for a spec that is malformed or too long for a target."""
    if not spec.tool or not 1 <= len(spec.track) <= 8 or len(set(spec.track)) != len(spec.track):
        raise ValueError("a read names a tool and 1 to 8 distinct tracked fields")
    if spec.path is not None and len(spec.path) > _MAX_PATH:
        raise ValueError(f"a path is at most {_MAX_PATH} keys")
    body: dict[str, object] = {"arguments": dict(spec.arguments), "tool": spec.tool, "track": list(spec.track)}
    if spec.path is not None:
        body["path"] = list(spec.path)
    target = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(target) > MAX_TARGET:
        raise ValueError(f"a read is at most {MAX_TARGET} characters as a target")
    return target


def parse(target: str) -> ReadSpec:
    """The spec a `target` holds. Raises ValueError for any other text."""
    try:
        raw = as_map(json.loads(target))
    except json.JSONDecodeError as e:
        raise ValueError("not a tool read") from e
    if raw is None or set(raw) - {"arguments", "tool", "track", "path"}:
        raise ValueError("not a tool read")
    tool, arguments, track = raw.get("tool"), as_map(raw.get("arguments")), texts(raw.get("track"))
    path = texts(raw.get("path"))
    if not isinstance(tool, str) or arguments is None or not track or (raw.get("path") is not None and path is None):
        raise ValueError("not a tool read")
    return ReadSpec(tool, arguments, tuple(track), None if path is None else tuple(path))


def texts(raw: object) -> list[str] | None:
    """`raw` as a list of text, None when it is not one."""
    found = as_list(raw)
    return [t for t in found if isinstance(t, str)] if found is not None and all(isinstance(t, str) for t in found) else None
