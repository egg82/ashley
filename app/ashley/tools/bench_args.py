"""A bench tool's arguments, as the model sent them, made into the Workshop's own Command by her: the same Commands a
person's routes build (`api.bench_commands`). Lengths, kinds and NULs are `decide`'s to judge; this checks only shapes."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_args

from ..inference.model import ToolSpec
from ..workshop.commands import Add, Archive, Command, Cue, CueAction, Edit, Link, Move, Remove, Rename, Restore, Undo, Unlink
from ..workshop.json_shape import list_of, object_of
from ..workshop.model import HER, Place, Text
from .tainted import her


class BadArguments(Exception):
    """An argument is missing or of the wrong type. The message names the argument, never its value."""


def command_of(name: str, args: Mapping[str, object]) -> Command:
    """The Command tool `name` (one of `COMMAND_TOOLS`) asks for, by her. Raises BadArguments; KeyError for any other
    name."""
    return _BUILDERS[name](args)


def check_names(args: Mapping[str, object], spec: ToolSpec) -> None:
    """Raises BadArguments naming the first argument `spec` does not define."""
    properties = spec.parameters.get("properties")
    loose: Any = properties
    known = {str(key) for key in dict[object, object](loose)} if isinstance(properties, dict) else set[str]()
    unknown = sorted(str(key) for key in args if key not in known)
    if unknown:
        raise BadArguments(f"{unknown[0]} is not an argument of {spec.name}")


def piece_id_of(args: Mapping[str, object]) -> int:
    """The `piece_id` argument. Raises BadArguments."""
    return _int(args, "piece_id")


def finding_id_of(args: Mapping[str, object]) -> int:
    """The `finding_id` argument. Raises BadArguments."""
    return _int(args, "finding_id")


@dataclass(frozen=True)
class Replacement:
    """`old` (not empty) to be replaced by `new` in piece `piece_id`, as it was at `base_version`."""

    piece_id: int
    base_version: int
    old: str
    new: str


def replacement_of(args: Mapping[str, object]) -> Replacement:
    """The arguments of `bench_replace`. Raises BadArguments."""
    old = _str(args, "old")
    if not old:
        raise BadArguments("old is not empty")
    return Replacement(_int(args, "piece_id"), _int(args, "base_version"), old, _str(args, "new"))


def result_of(args: Mapping[str, object]) -> int:
    """The `result` argument, a search result's number. Raises BadArguments."""
    return _int(args, "result")


def quote_of(args: Mapping[str, object]) -> str:
    """The `quote` argument, which may be empty. Raises BadArguments."""
    return _str(args, "quote")


def start_of(args: Mapping[str, object]) -> int | None:
    """The optional `start` of a video, in seconds, None when absent. Raises BadArguments."""
    return _int(args, "start") if "start" in args else None


def offset_of(args: Mapping[str, object]) -> int:
    """The optional `offset` of a read window, 0 when absent. Raises BadArguments."""
    offset = _int(args, "offset") if "offset" in args else 0
    if offset < 0:
        raise BadArguments("offset is 0 or more")
    return offset


def seq_of(args: Mapping[str, object]) -> int:
    """The `seq` argument. Raises BadArguments."""
    return _int(args, "seq")


def whole_turn_of(args: Mapping[str, object]) -> bool:
    """The optional `whole_turn` of `bench_undo`, False when absent. Raises BadArguments."""
    value = args.get("whole_turn", False)
    if not isinstance(value, bool):
        raise BadArguments("whole_turn is true or false")
    return value


@dataclass(frozen=True)
class NewLink:
    """A link `bench_add` makes from the piece it adds: of `kind` to piece `to_id`."""

    kind: str
    to_id: int


def new_links_of(args: Mapping[str, object]) -> tuple[NewLink, ...]:
    """The optional `links` of `bench_add`, each `{"kind", "to"}`; none when absent. Raises BadArguments."""
    items = list_of(args.get("links", []))
    if items is None:
        raise BadArguments("links is a list of {kind, to}")
    found: list[NewLink] = []
    for item in items:
        entry = object_of(item)
        if entry is None or set(entry) != {"kind", "to"}:
            raise BadArguments("each of links is exactly {kind, to}")
        found.append(NewLink(_str(entry, "kind"), _int(entry, "to")))
    return tuple(found)


def _add(args: Mapping[str, object]) -> Command:
    return Add(her(), _str(args, "kind"), Text(_str(args, "title"), _str(args, "body")))


def _edit(args: Mapping[str, object]) -> Command:
    return Edit(her(), _int(args, "piece_id"), _int(args, "base_version"), Text(_str(args, "title"), _str(args, "body")))


def _move(args: Mapping[str, object]) -> Command:
    order = _int(args, "order")
    if order < 0:
        raise BadArguments("order is 0 or more")
    return Move(HER, _int(args, "piece_id"), Place(order))


def _remove(args: Mapping[str, object]) -> Command:
    return Remove(HER, _int(args, "piece_id"))


def _archive(args: Mapping[str, object]) -> Command:
    return Archive(HER, _int(args, "piece_id"))


def _restore(args: Mapping[str, object]) -> Command:
    return Restore(HER, _int(args, "piece_id"))


def _undo(args: Mapping[str, object]) -> Command:
    return Undo(HER, _int(args, "seq"))


def _rename(args: Mapping[str, object]) -> Command:
    return Rename(HER, _str(args, "title"))


def _link(args: Mapping[str, object]) -> Command:
    unlink = args.get("unlink", False)
    if not isinstance(unlink, bool):
        raise BadArguments("unlink is true or false")
    return (Unlink if unlink else Link)(HER, _int(args, "from_id"), _str(args, "kind"), _int(args, "to_id"))


def _cue(args: Mapping[str, object]) -> Command:
    action = args.get("action")
    for known in get_args(CueAction):
        if action == known:
            return Cue(HER, _int(args, "piece_id"), known, _seconds(args))
    raise BadArguments("action is one of " + ", ".join(get_args(CueAction)))


def _seconds(args: Mapping[str, object]) -> float | None:
    value = args.get("seconds")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadArguments("seconds is a number")
    return float(value)


def _str(args: Mapping[str, object], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise BadArguments(f"{key} is a string")
    return value


def _int(args: Mapping[str, object], key: str) -> int:
    value = args.get(key)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadArguments(f"{key} is a whole number")
    return value


_BUILDERS = {"bench_add": _add, "bench_edit": _edit, "bench_move": _move, "bench_remove": _remove,
             "bench_archive": _archive, "bench_restore": _restore, "bench_undo": _undo, "bench_rename": _rename, "bench_cue": _cue,
             "bench_link": _link}
COMMAND_TOOLS: tuple[str, ...] = tuple(_BUILDERS)
