"""Home Assistant's JSON as the House adapter reads it: every value arrives as `object`, and these narrow it without
trusting its shape. A missing or wrongly typed value reads as empty (an empty string, list or object), so one odd record
never fails a whole listing."""

from datetime import datetime
from typing import Any

JsonObject = dict[str, object]


def is_object(value: object) -> bool:
    return isinstance(value, dict)


def is_list(value: object) -> bool:
    return isinstance(value, list)


def obj(value: object) -> JsonObject:
    """`value` as an object with string keys; empty when it is not one."""
    loose: Any = value
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in dict[object, object](loose).items()}


def listed(value: object) -> list[object]:
    """`value` as a list; empty when it is not one."""
    loose: Any = value
    return list[object](loose) if isinstance(value, list) else []


def rows(value: object) -> list[JsonObject]:
    """The objects in `value`, a list."""
    return [obj(item) for item in listed(value) if is_object(item)]


def text(value: object) -> str:
    return value if isinstance(value, str) else ""


def names(value: object) -> tuple[str, ...]:
    """The non-empty strings in `value`, a list."""
    return tuple(item for item in listed(value) if isinstance(item, str) and item)


def moment(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
