"""A screen's touch buttons as the body of a `controls` piece: a JSON list of `{"id", "label", "action", "entity_id"}`.

`id` is 1 to 40 of `[a-z0-9-]`, unique in the list; `label` 1 to 40 characters once stripped; `action` one of
`ACTIONS`' keys; `entity_id` a non-empty string. At most `MAX_CONTROLS`. This module checks the shape only: whether an
entity is in the house, and in the action's domain, is the caller's, before it builds the Command."""

import json
import re
from dataclasses import dataclass
from typing import Literal, get_args

from .json_shape import list_of, object_of

Action = Literal["light.turn_on", "light.turn_off", "scene.turn_on"]
ACTIONS: dict[str, Action] = {a: a for a in get_args(Action)}
MAX_CONTROLS = 12
ID = re.compile(r"[a-z0-9-]{1,40}")
_KEYS = {"id", "label", "action", "entity_id"}


@dataclass(frozen=True)
class Control:
    """One button: run `action` on the entity `entity_id`."""

    id: str
    label: str
    action: Action
    entity_id: str


def well_formed(body: str) -> bool:
    """Whether `body` is a list of at most `MAX_CONTROLS` controls of the shape above, with unique ids."""
    return _parsed(body) is not None


def decode(body: str) -> tuple[Control, ...]:
    """The controls `body` holds, in order. Raises ValueError when it is not well formed."""
    found = _parsed(body)
    if found is None:
        raise ValueError("not a list of controls")
    return found


def encode(controls: tuple[Control, ...]) -> str:
    """The body holding `controls`, in order."""
    return json.dumps([{"id": c.id, "label": c.label, "action": c.action, "entity_id": c.entity_id} for c in controls],
                      ensure_ascii=False, separators=(",", ":"))


def _parsed(body: str) -> tuple[Control, ...] | None:
    try:
        raw: object = json.loads(body)
    except ValueError:
        return None
    items = list_of(raw)
    if items is None or len(items) > MAX_CONTROLS:
        return None
    out = [_control(item) for item in items]
    if any(c is None for c in out) or len({c.id for c in out if c is not None}) != len(out):
        return None
    return tuple(c for c in out if c is not None)


def _control(item: object) -> Control | None:
    fields = object_of(item)
    if fields is None or set(fields) != _KEYS:
        return None
    ident, label, action, entity = fields["id"], fields["label"], fields["action"], fields["entity_id"]
    if not (isinstance(ident, str) and ID.fullmatch(ident) and isinstance(label, str) and 1 <= len(label.strip()) <= 40
            and isinstance(action, str) and action in ACTIONS and isinstance(entity, str) and entity):
        return None
    return Control(ident, label, ACTIONS[action], entity)
