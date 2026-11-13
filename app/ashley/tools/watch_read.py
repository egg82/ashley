"""The `read` argument of `watch` for the `tool` kind: which of her read-only tools to run, with what fixed arguments,
which list in its answer holds the items, and which fields of each item to track (the first names the item). Shapes
only: a bad one raises `BadArguments` naming the argument, never its value."""

from collections.abc import Mapping

from ..criteria.predicates import as_map
from ..watches.tool_target import HASH, ReadSpec, target_of, texts
from .bench_args import BadArguments

_FIELDS = ("tool", "arguments", "path", "track")
READ: dict[str, object] = {
    "type": "object",
    "description": ("For kind tool: the read of one of your tools that only reads, run again and again with these "
                    "arguments. tool and arguments are the call as you would make it. For an answer that holds a list, path "
                    "gives the keys down to that list (for house_ask: response, the thing's id, then its list, such "
                    "as events; [] when the answer is the list) and track names the fields of each item to keep; "
                    "the first one tells one item from another, so it must differ between items. Leave path and "
                    "track out and the whole answer is one item, so any change wakes you."),
    "properties": {
        "tool": {"type": "string"},
        "arguments": {"type": "object"},
        "path": {"type": "array", "items": {"type": "string"}},
        "track": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tool"],
}


def parse(raw: object) -> ReadSpec:
    """The spec `read` asks for, its target built here. Raises BadArguments."""
    got = as_map(raw)
    if got is None:
        raise BadArguments("read is an object with tool, arguments, path and track")
    extra = sorted(k for k in got if k not in _FIELDS)
    if extra:
        raise BadArguments(f"{extra[0]} is not a field of read")
    tool, arguments = got.get("tool"), as_map(got.get("arguments", {}))
    if not isinstance(tool, str) or not tool.strip():
        raise BadArguments("read.tool is a tool name")
    if arguments is None:
        raise BadArguments("read.arguments is an object")
    if got.get("path") is None and got.get("track") is not None:
        raise BadArguments("read.track needs read.path")
    path = None if got.get("path") is None else _names(got, "path")
    spec = ReadSpec(tool.strip(), arguments, (HASH,) if path is None else _names(got, "track"), path)
    try:
        target_of(spec)
    except ValueError as e:
        raise BadArguments(str(e)) from e
    return spec


def _names(raw: Mapping[str, object], key: str) -> tuple[str, ...]:
    found = texts(raw.get(key))
    if found is None or not all(n.strip() for n in found):
        raise BadArguments(f"read.{key} is a list of names")
    return tuple(n.strip() for n in found)
