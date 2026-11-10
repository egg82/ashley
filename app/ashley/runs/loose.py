"""JSON from outside (the Kubernetes API, the runner's line) as typed values, checked before anything reads them."""

from typing import Any


def as_object(value: object) -> dict[str, Any] | None:
    """`value` as a JSON object with string keys, or None when it is not one."""
    loose: Any = value
    if not isinstance(value, dict):
        return None
    return {str(k): v for k, v in dict[Any, Any](loose).items()}


def as_list(value: object) -> list[Any] | None:
    loose: Any = value
    return list[Any](loose) if isinstance(value, list) else None
