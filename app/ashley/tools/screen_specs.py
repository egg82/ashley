"""Her screen tools as the model is offered them. The kinds come from the screen rules, so a new screen kind in
`kinds.json` is offered without a change here."""

from collections.abc import Mapping

from ..inference.model import ToolSpec
from ..workshop.model import SIZES
from ..workshop.rules import Rules
from ..workshop.screen_controls import ACTIONS

INSTRUCTIONS = (
    "You arrange the touch screen in the hall, as you arrange a bench: screen_read shows its pieces in order, each with a "
    "size, and what can be added. What you change shows on the hall screen at once and can be undone with screen_undo, "
    "so when you are asked to put something up, take it down, make it bigger or move it, do it and say what you did; "
    "there is nothing to confirm first. Anyone in the hall sees that screen. Pieces whose last_changed_by is person stay "
    "where they left them unless you are asked to move them. The conversation is never taken off the screen, so the hall "
    "can always ask you to put things back. The buttons are a piece too: screen_buttons replaces the whole list, naming the "
    "version you read, and each light or scene must be one of the house's. With more than one screen, name the screen "
    "by device_id.")

_INT: Mapping[str, object] = {"type": "integer"}
_DEVICE: Mapping[str, object] = {"type": "integer", "description": "the screen's device id; left out when only one "
                                 "screen is in reach"}
_SIZE: Mapping[str, object] = {"type": "string", "enum": list(SIZES),
                               "description": "share of the row: small a quarter, medium a half, large three "
                                              "quarters, full the whole row"}
_BUTTON: Mapping[str, object] = {
    "type": "object",
    "properties": {"id": {"type": "string", "description": "the button's key when it already has one; left out for a new button"},
                   "label": {"type": "string", "description": "what the button says, 1 to 40 characters"},
                   "action": {"type": "string", "enum": list(ACTIONS)},
                   "entity_id": {"type": "string", "description": "the light or scene, as the house calls it"}},
    "required": ["label", "action", "entity_id"]}


def _object(properties: Mapping[str, object], required: tuple[str, ...]) -> Mapping[str, object]:
    return {"type": "object", "properties": dict(properties), "required": list(required)}


def specs(rules: Rules) -> tuple[ToolSpec, ...]:
    kind: Mapping[str, object] = {"type": "string", "enum": list(rules.kinds)}
    return (
        ToolSpec("screen_read", "Read a screen: its pieces in order (id, kind, order, size, who last changed it), each "
                 "controls piece's buttons and version, the seq screen_undo would take back, and the kinds that can be "
                 "added. With no device_id and more than one screen in reach, lists the screens instead.",
                 _object({"device_id": _DEVICE}, ()), reads=True, outside=False),
        ToolSpec("screen_add", "Add a piece to the end of a screen, at a size. A kind already on the screen is refused.",
                 _object({"device_id": _DEVICE, "kind": kind, "size": _SIZE}, ("kind", "size")), outside=False, tier="judged"),
        ToolSpec("screen_move", "Put a piece at `order` among the screen's pieces (0 first) at a size.",
                 _object({"device_id": _DEVICE, "piece_id": _INT, "order": _INT, "size": _SIZE},
                         ("piece_id", "order", "size")), outside=False, tier="judged"),
        ToolSpec("screen_remove", "Take a piece off a screen. The conversation cannot be taken off.",
                 _object({"device_id": _DEVICE, "piece_id": _INT}, ("piece_id",)), outside=False, tier="judged"),
        ToolSpec("screen_buttons", "Replace the whole list of touch buttons in a controls piece, based on the version "
                 "screen_read gave. Each button runs one action on one light or scene of the house.",
                 _object({"device_id": _DEVICE, "piece_id": _INT, "base_version": _INT,
                          "buttons": {"type": "array", "items": _BUTTON}}, ("piece_id", "base_version", "buttons")),
                 outside=False, tier="judged"),
        ToolSpec("screen_undo", "Take back the screen's latest change that can be taken back.",
                 _object({"device_id": _DEVICE}, ()), outside=False, tier="judged"),
    )
