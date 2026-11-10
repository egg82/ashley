"""An automation piece's body: Home Assistant's automation config as a JSON object, in HA's own field names (`alias`,
`description`, `triggers`, `conditions`, `actions`, `mode`, and the optional `max`, `max_exceeded`, `variables`,
`trigger_variables`). Only the shape is checked here: each field's type, every trigger, condition and action an object,
and no field HA would not take or that the install owns (`id`). What a trigger or action means is HA's to judge when
the config is written, except a wake action, whose data is hers to check (`wake_action`). An empty body is a draft and
passes; installing needs an alias, a trigger and an action."""

import json
from collections.abc import Mapping
from typing import Any

from . import wake_action

MODES = ("single", "restart", "queued", "parallel")
_LISTS = ("triggers", "conditions", "actions")
_STRINGS = ("alias", "description", "max_exceeded")
_OBJECTS = ("variables", "trigger_variables")
FIELDS = frozenset((*_STRINGS, *_LISTS, *_OBJECTS, "mode", "max"))
_SINGULAR = {"trigger": "triggers", "condition": "conditions", "action": "actions"}


def config_of(body: str) -> dict[str, Any] | None:
    """The config `body` holds; None when it is not a JSON object of the shape above (or is empty)."""
    try:
        loaded = object_of(json.loads(body))
    except ValueError:
        return None
    return loaded if loaded is not None and _shaped(loaded) else None


def object_of(data: object) -> dict[str, Any] | None:
    """`data` as a JSON object; None when it is not one."""
    loose: Any = data
    return {str(k): v for k, v in dict[object, object](loose).items()} if isinstance(data, dict) else None


def well_formed(body: str) -> bool:
    """Whether `body` is empty or a config of the shape above."""
    return not body.strip() or config_of(body) is not None


def complete(body: str) -> bool:
    """Whether `body` is a config that can be installed: well formed, with a non-blank alias, a trigger and an action."""
    config = config_of(body)
    return (config is not None and isinstance(config.get("alias"), str) and bool(config["alias"].strip())
            and bool(config.get("triggers")) and bool(config.get("actions")))


def body_of(config: Mapping[str, Any]) -> str:
    """A config read from Home Assistant as a piece's body: its `id` dropped (an install sets its own) and the older
    singular names (`trigger`, `condition`, `action`) given as HA's plural ones."""
    renamed = {_SINGULAR.get(k, k): v for k, v in config.items() if k != "id"}
    return json.dumps(renamed, indent=2, ensure_ascii=False)


def _shaped(config: Mapping[str, Any]) -> bool:
    if not set(config) <= FIELDS:
        return False
    if any(k in config and not isinstance(config[k], str) for k in _STRINGS):
        return False
    if any(k in config and not _objects(config[k]) for k in _LISTS):
        return False
    if any(k in config and not isinstance(config[k], dict) for k in _OBJECTS):
        return False
    if "mode" in config and config["mode"] not in MODES:
        return False
    if "max" in config and not (type(config["max"]) is int and config["max"] >= 1):
        return False
    return wake_action.well_formed(config)


def _objects(value: object) -> bool:
    loose: Any = value
    return isinstance(value, list) and all(isinstance(item, dict) for item in loose)
