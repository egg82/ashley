"""Commands and Effects as JSON objects, for the command log's `command` and `effect` columns. Who made a command is
its row's `person_id`, not part of the object. `decode_*` reads only what `encode_*` wrote. A place's `pin` and `box`
are written only when set, and a move's only when it sets or clears them (null), so a row from before pins decodes as
a place without them and a move that keeps them."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any, get_args

from .commands import (Add, Added, Archive, Archived, Command, Cue, CueAction, Cued, Edit, Edited, Effect, Install,
                       Installed, KEEP, Keep, Link, Linked, Move, Moved, Point, Pointed, Propose, Proposed, Ran, Remove, Removed, Rename,
                       Renamed, Restore, Restored, Run, Shown, ShownRow, Surfaced, Undo, Uninstalled, Unlink, Unlinked, type_of)
from .links import PieceLink
from .model import SIZES, Box, By, Piece, Pin, Place, Size, Text
from .reader import Passage

Json = dict[str, Any]


def encode_command(command: Command) -> Json:
    """The command as JSON; the runner's carries `runner`, since `decide` judges a `by_code` kind by it, and a change made in a turn
    carries `turn`."""
    return {**_encode(command), **({"runner": True} if command.by.runner else {}),
            **({"turn": command.by.turn} if command.by.turn is not None else {})}


def _encode(command: Command) -> Json:
    out: Json = {"type": type_of(command)}
    if isinstance(command, Add):
        return {**out, "kind": command.kind, **_text(command.text), **_sized(command.size)}
    if isinstance(command, Undo):
        return {**out, "seq": command.seq}
    if isinstance(command, Rename):
        return {**out, "title": command.title}
    if isinstance(command, (Link, Unlink)):
        return {**out, **_link(command.link)}
    out["piece_id"] = command.piece_id
    if isinstance(command, Cue):
        return {**out, "action": command.action, "seconds": command.seconds}
    if isinstance(command, Point):
        return {**out, "base_version": command.base_version, "passage": _passage(command.passage)}
    if isinstance(command, Surfaced):
        return {**out, "rows": _rows(command.rows)}
    if isinstance(command, Move):
        return {**out, "place": _place(command.place), **_kept("pin", command.pin, _pin),
                **_kept("box", command.box, _box)}
    if isinstance(command, Edit):
        return {**out, "base_version": command.base_version, **_text(command.text)}
    if isinstance(command, Run):
        return {**out, "base_version": command.base_version, "language": command.language}
    if isinstance(command, Propose):
        return {**out, "base_version": command.base_version, "enabled": command.enabled, "turn_off": command.turn_off,
                "shadow": command.shadow}
    if isinstance(command, Install):
        return {**out, "proposal": command.proposal, "automation_id": command.automation_id}
    return out


def decode_command(raw: Json, by: By) -> Command:
    turn = raw.get("turn")
    by = replace(by, runner=True) if raw.get("runner") is True else by
    return _decode(raw, by if not isinstance(turn, int) else replace(by, turn=turn))


def _decode(raw: Json, by: By) -> Command:
    kind = raw["type"]
    if kind == "add":
        return Add(by, str(raw["kind"]), _text_of(raw), _size(raw.get("size")))
    if kind == "remove":
        return Remove(by, int(raw["piece_id"]))
    if kind == "move":
        pin = _pin_of(raw["pin"]) if "pin" in raw else KEEP
        box = _box_of(raw["box"]) if "box" in raw else KEEP
        return Move(by, int(raw["piece_id"]), _place_of(raw["place"]), pin, box)
    if kind == "edit":
        return Edit(by, int(raw["piece_id"]), int(raw["base_version"]), _text_of(raw))
    if kind == "run":
        return Run(by, int(raw["piece_id"]), int(raw["base_version"]), str(raw["language"]))
    if kind == "propose":
        return Propose(by, int(raw["piece_id"]), int(raw["base_version"]), bool(raw["enabled"]), _maybe(raw["turn_off"]),
                       bool(raw.get("shadow", False)))
    if kind == "install":
        return Install(by, int(raw["piece_id"]), int(raw["proposal"]), str(raw["automation_id"]))
    if kind == "cue":
        return Cue(by, int(raw["piece_id"]), _action(raw["action"]), _seconds(raw["seconds"]))
    if kind == "point":
        return Point(by, int(raw["piece_id"]), int(raw["base_version"]), _passage_of(raw["passage"]))
    if kind == "surfaced":
        return Surfaced(by, int(raw["piece_id"]), _rows_of(raw["rows"]))
    if kind == "archive":
        return Archive(by, int(raw["piece_id"]))
    if kind == "restore":
        return Restore(by, int(raw["piece_id"]))
    if kind == "undo":
        return Undo(by, int(raw["seq"]))
    if kind == "rename":
        return Rename(by, str(raw["title"]))
    if kind in ("link", "unlink"):
        link = _link_of(raw)
        return (Link if kind == "link" else Unlink)(by, link.from_id, link.kind, link.to_id)
    raise ValueError(f"unknown command type {kind!r}")


def encode_effect(effect: Effect) -> Json:
    if isinstance(effect, Added):
        return {"type": "added", "piece": _piece(effect.piece)}
    if isinstance(effect, Removed):
        return {"type": "removed", "piece": _piece(effect.piece)}
    if isinstance(effect, Edited):
        return {"type": "edited", "piece_id": effect.piece_id, "before": _text(effect.before),
                "after": _text(effect.after), **({"outside": True} if effect.outside else {})}
    if isinstance(effect, Archived):
        return {"type": "archived", "piece": _piece(effect.piece)}
    if isinstance(effect, Restored):
        return {"type": "restored", "piece": _piece(effect.piece)}
    if isinstance(effect, Renamed):
        return {"type": "renamed", "before": effect.before, "after": effect.after}
    if isinstance(effect, Linked):
        return {"type": "linked", **_link(effect.link)}
    if isinstance(effect, Unlinked):
        return {"type": "unlinked", **_link(effect.link)}
    if isinstance(effect, Ran):
        return {"type": "ran", "piece_id": effect.piece_id, "version": effect.version}
    if isinstance(effect, Cued):
        return {"type": "cued", "piece_id": effect.piece_id, "action": effect.action, "seconds": effect.seconds}
    if isinstance(effect, Pointed):
        return {"type": "pointed", "piece_id": effect.piece_id, "version": effect.version,
                "passage": _passage(effect.passage)}
    if isinstance(effect, Shown):
        return {"type": "shown", "piece_id": effect.piece_id, "rows": _rows(effect.rows)}
    if isinstance(effect, Proposed):
        return {"type": "proposed", "piece_id": effect.piece_id, "version": effect.version, "enabled": effect.enabled,
                "turn_off": effect.turn_off, "shadow": effect.shadow}
    if isinstance(effect, Installed):
        return {"type": "installed", "piece_id": effect.piece_id, "version": effect.version,
                "automation_id": effect.automation_id, "enabled": effect.enabled, "turn_off": effect.turn_off,
                "proposal": effect.proposal, "shadow": effect.shadow}
    if isinstance(effect, Uninstalled):
        return {"type": "uninstalled", "piece_id": effect.piece_id, "install": effect.install,
                "automation_id": effect.automation_id}
    return {"type": "moved", "piece_id": effect.piece_id, "before": _place(effect.before),
            "after": _place(effect.after)}


def decode_effect(raw: Json) -> Effect:
    kind = raw["type"]
    if kind == "added":
        return Added(_piece_of(raw["piece"]))
    if kind == "removed":
        return Removed(_piece_of(raw["piece"]))
    if kind == "edited":
        return Edited(int(raw["piece_id"]), _text_of(raw["before"]), _text_of(raw["after"]), raw.get("outside") is True)
    if kind == "archived":
        return Archived(_piece_of(raw["piece"]))
    if kind == "restored":
        return Restored(_piece_of(raw["piece"]))
    if kind == "renamed":
        return Renamed(str(raw["before"]), str(raw["after"]))
    if kind == "linked":
        return Linked(_link_of(raw))
    if kind == "unlinked":
        return Unlinked(_link_of(raw))
    if kind == "ran":
        return Ran(int(raw["piece_id"]), int(raw["version"]))
    if kind == "cued":
        return Cued(int(raw["piece_id"]), _action(raw["action"]), _seconds(raw["seconds"]))
    if kind == "pointed":
        return Pointed(int(raw["piece_id"]), int(raw["version"]), _passage_of(raw["passage"]))
    if kind == "shown":
        return Shown(int(raw["piece_id"]), _rows_of(raw["rows"]))
    if kind == "proposed":
        return Proposed(int(raw["piece_id"]), int(raw["version"]), bool(raw["enabled"]), _maybe(raw["turn_off"]),
                        bool(raw.get("shadow", False)))
    if kind == "installed":
        return Installed(int(raw["piece_id"]), int(raw["version"]), str(raw["automation_id"]), bool(raw["enabled"]),
                         _maybe(raw["turn_off"]), int(raw["proposal"]), bool(raw.get("shadow", False)))
    if kind == "uninstalled":
        return Uninstalled(int(raw["piece_id"]), int(raw["install"]), str(raw["automation_id"]))
    if kind == "moved":
        return Moved(int(raw["piece_id"]), _place_of(raw["before"]), _place_of(raw["after"]))
    raise ValueError(f"unknown effect type {kind!r}")


def _action(raw: object) -> CueAction:
    for action in get_args(CueAction):
        if action == raw:
            return action
    raise ValueError(f"unknown cue action {raw!r}")


def _seconds(raw: Any) -> float | None:
    return None if raw is None else float(raw)


def _passage(passage: Passage | None) -> Json | None:
    return None if passage is None else {"paragraph": passage.paragraph, "start": passage.start, "end": passage.end}


def _passage_of(raw: Json | None) -> Passage | None:
    return None if raw is None else Passage(int(raw["paragraph"]), int(raw["start"]), int(raw["end"]))


def _rows(rows: tuple[ShownRow, ...]) -> list[Json]:
    return [{"name": r.name, "value": r.value} for r in rows]


def _rows_of(raw: list[Json]) -> tuple[ShownRow, ...]:
    return tuple(ShownRow(str(r["name"]), str(r["value"])) for r in raw)


def _maybe(raw: object) -> str | None:
    return None if raw is None else str(raw)


def _link(link: PieceLink) -> Json:
    """A link's fields; never `piece_id`, so the log's per-piece queries pass a link's rows by (`postgres_rows`)."""
    return {"from_id": link.from_id, "kind": link.kind, "to_id": link.to_id}


def _link_of(raw: Json) -> PieceLink:
    return PieceLink(int(raw["from_id"]), str(raw["kind"]), int(raw["to_id"]))


def _text(text: Text) -> Json:
    return {"title": text.title, "body": text.body}


def _text_of(raw: Json) -> Text:
    return Text(str(raw["title"]), str(raw["body"]))


def _place(place: Place) -> Json:
    return {"order": place.order, **_sized(place.size), **({} if place.pin is None else {"pin": _pin(place.pin)}),
            **({} if place.box is None else {"box": _box(place.box)})}


def _place_of(raw: Json) -> Place:
    return Place(int(raw["order"]), _size(raw.get("size")), _pin_of(raw.get("pin")), _box_of(raw.get("box")))


def _kept[T](name: str, value: T | None | Keep, encode: Callable[[T], Json]) -> Json:
    """A move's `name` field: nothing when it keeps the piece's, null when it clears it."""
    if isinstance(value, Keep):
        return {}
    return {name: None if value is None else encode(value)}


def _pin(pin: Pin) -> Json:
    return {"x": pin.x, "y": pin.y}


def _pin_of(raw: Json | None) -> Pin | None:
    return None if raw is None else Pin(int(raw["x"]), int(raw["y"]))


def _box(box: Box) -> Json:
    return {"w": box.w, "h": box.h}


def _box_of(raw: Json | None) -> Box | None:
    return None if raw is None else Box(int(raw["w"]), int(raw["h"]))


def _sized(size: Size | None) -> Json:
    return {} if size is None else {"size": size}


def _size(raw: object) -> Size | None:
    if raw is None:
        return None
    for size in SIZES:
        if size == raw:
            return size
    raise ValueError(f"unknown size {raw!r}")


def _piece(piece: Piece) -> Json:
    return {"id": piece.id, "kind": piece.kind, **_text(piece.text), "version": piece.version,
            "place": _place(piece.place), "changed_by": piece.changed_by,
            **({"outside": True} if piece.outside else {})}


def _piece_of(raw: Json) -> Piece:
    return Piece(int(raw["id"]), str(raw["kind"]), _text_of(raw), int(raw["version"]), _place_of(raw["place"]),
                 int(raw["changed_by"]), raw.get("outside") is True)
