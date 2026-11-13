"""Commands and Effects as JSON objects, for the command log's `command` and `effect` columns. Who made a command is
its row's `person_id`, not part of the object. `decode_*` reads only what `encode_*` wrote."""

from dataclasses import replace
from typing import Any, get_args

from .commands import (Add, Added, Archive, Archived, Command, Cue, CueAction, Cued, Edit, Edited, Effect, Install,
                       Installed, Move, Moved, Point, Pointed, Propose, Proposed, Ran, Remove, Removed, Rename, Renamed, Restore,
                       Restored, Run, Shown, ShownRow, Surfaced, Undo, Uninstalled, type_of)
from .model import SIZES, By, Piece, Place, Size, Text
from .reader import Passage

Json = dict[str, Any]


def encode_command(command: Command) -> Json:
    """The command as JSON; the runner's carries `runner`, since `decide` judges a `by_code` kind by it."""
    return {**_encode(command), **({"runner": True} if command.by.runner else {})}


def _encode(command: Command) -> Json:
    out: Json = {"type": type_of(command)}
    if isinstance(command, Add):
        return {**out, "kind": command.kind, **_text(command.text), "size": command.size}
    if isinstance(command, Undo):
        return {**out, "seq": command.seq}
    if isinstance(command, Rename):
        return {**out, "title": command.title}
    out["piece_id"] = command.piece_id
    if isinstance(command, Cue):
        return {**out, "action": command.action, "seconds": command.seconds}
    if isinstance(command, Point):
        return {**out, "base_version": command.base_version, "passage": _passage(command.passage)}
    if isinstance(command, Surfaced):
        return {**out, "rows": _rows(command.rows)}
    if isinstance(command, Move):
        return {**out, "place": _place(command.place)}
    if isinstance(command, Edit):
        return {**out, "base_version": command.base_version, **_text(command.text)}
    if isinstance(command, Run):
        return {**out, "base_version": command.base_version, "language": command.language}
    if isinstance(command, Propose):
        return {**out, "base_version": command.base_version, "enabled": command.enabled, "turn_off": command.turn_off}
    if isinstance(command, Install):
        return {**out, "proposal": command.proposal, "automation_id": command.automation_id}
    return out


def decode_command(raw: Json, by: By) -> Command:
    return _decode(raw, replace(by, runner=True) if raw.get("runner") is True else by)


def _decode(raw: Json, by: By) -> Command:
    kind = raw["type"]
    if kind == "add":
        return Add(by, str(raw["kind"]), _text_of(raw), _size(raw["size"]))
    if kind == "remove":
        return Remove(by, int(raw["piece_id"]))
    if kind == "move":
        return Move(by, int(raw["piece_id"]), _place_of(raw["place"]))
    if kind == "edit":
        return Edit(by, int(raw["piece_id"]), int(raw["base_version"]), _text_of(raw))
    if kind == "run":
        return Run(by, int(raw["piece_id"]), int(raw["base_version"]), str(raw["language"]))
    if kind == "propose":
        return Propose(by, int(raw["piece_id"]), int(raw["base_version"]), bool(raw["enabled"]), _maybe(raw["turn_off"]))
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
                "turn_off": effect.turn_off}
    if isinstance(effect, Installed):
        return {"type": "installed", "piece_id": effect.piece_id, "version": effect.version,
                "automation_id": effect.automation_id, "enabled": effect.enabled, "turn_off": effect.turn_off,
                "proposal": effect.proposal}
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
    if kind == "ran":
        return Ran(int(raw["piece_id"]), int(raw["version"]))
    if kind == "cued":
        return Cued(int(raw["piece_id"]), _action(raw["action"]), _seconds(raw["seconds"]))
    if kind == "pointed":
        return Pointed(int(raw["piece_id"]), int(raw["version"]), _passage_of(raw["passage"]))
    if kind == "shown":
        return Shown(int(raw["piece_id"]), _rows_of(raw["rows"]))
    if kind == "proposed":
        return Proposed(int(raw["piece_id"]), int(raw["version"]), bool(raw["enabled"]), _maybe(raw["turn_off"]))
    if kind == "installed":
        return Installed(int(raw["piece_id"]), int(raw["version"]), str(raw["automation_id"]), bool(raw["enabled"]),
                         _maybe(raw["turn_off"]), int(raw["proposal"]))
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


def _text(text: Text) -> Json:
    return {"title": text.title, "body": text.body}


def _text_of(raw: Json) -> Text:
    return Text(str(raw["title"]), str(raw["body"]))


def _place(place: Place) -> Json:
    return {"order": place.order, "size": place.size}


def _place_of(raw: Json) -> Place:
    return Place(int(raw["order"]), _size(raw["size"]))


def _size(raw: object) -> Size:
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
