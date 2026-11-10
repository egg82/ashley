"""The action in an automation piece that wakes her: a call of Home Assistant's `rest_command.ashley_wake` (set up
once in HA's configuration to POST its data to `/api/wakes` with the house's device token), anywhere in the
automation's actions, nested ones included. Its data is structured, never free text: exactly `event` (a slug, the
event a wake rule answers, `wake_rule`) and `event_id` (a template HA renders per run, `{{ context.id }}`, which
makes a retry the same wake), and optionally `who` (a `person.*` entity id or a template), `what` (a slug or a
template) and `when` (a template). A template is one `{{ ... }}` expression and nothing around it; what it renders is
checked again where the wake arrives. Any action whose `action`, or HA's legacy `service`, names `ashley_wake` at all
is taken as a wake call, so one under the legacy key or a templated name is refused rather than passed unchecked: a
piece is written in HA's current names, as its top-level fields are."""

import re
from collections.abc import Mapping
from typing import Any

SERVICE = "rest_command.ashley_wake"
_NAME = "ashley_wake"
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PERSON = re.compile(r"person\.[a-z0-9_]+")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


def well_formed(config: Mapping[str, Any]) -> bool:
    """Whether every wake action in `config`'s actions has the shape above (true when there is none)."""
    return all(_action_ok(a) for a in _wakes(config.get("actions", [])))


def events_of(config: Mapping[str, Any]) -> tuple[str, ...]:
    """The events `config`'s wake actions send, in the order they appear."""
    return tuple(str(a["data"]["event"]) for a in _wakes(config.get("actions", [])) if _action_ok(a))


def _wakes(node: object) -> list[dict[str, Any]]:
    loose: Any = node
    if isinstance(node, list):
        return [w for item in loose for w in _wakes(item)]
    if not isinstance(node, dict):
        return []
    found = [w for value in loose.values() for w in _wakes(value)]
    return [loose, *found] if _calls_her(loose) else found


def _calls_her(node: Mapping[str, Any]) -> bool:
    return any(isinstance(node.get(k), str) and _NAME in node[k] for k in ("action", "service"))


_CHECKS: dict[str, tuple[re.Pattern[str], ...]] = {
    "event": (_SLUG,), "event_id": (_TEMPLATE,), "who": (_PERSON, _TEMPLATE), "what": (_SLUG, _TEMPLATE),
    "when": (_TEMPLATE,)}


def _action_ok(action: Mapping[str, Any]) -> bool:
    raw: object = action.get("data")
    loose: Any = raw
    if set(action) != {"action", "data"} or action["action"] != SERVICE or not isinstance(raw, dict):
        return False
    data: dict[str, object] = {str(k): v for k, v in dict[object, object](loose).items()}
    if not {"event", "event_id"} <= set(data) <= set(_CHECKS):
        return False
    return all(isinstance(v, str) and any(p.fullmatch(v) for p in _CHECKS[k]) for k, v in data.items())
