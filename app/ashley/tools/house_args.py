"""The arguments of her house tools, read as the model sent them. Each raises ValueError naming only the argument, never
its value."""

import json
from collections.abc import Mapping
from typing import Any


def only(arguments: Mapping[str, object], tool: str, names: tuple[str, ...]) -> None:
    unknown = sorted(k for k in arguments if k not in names)
    if unknown:
        raise ValueError(f"{tool} takes only {', '.join(names)}; not {', '.join(unknown)}")


def text(arguments: Mapping[str, object], key: str) -> str | None:
    """A string argument; None when it is left out or blank."""
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} is a string")
    return value.strip() or None


def required(arguments: Mapping[str, object], key: str) -> str:
    value = text(arguments, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def texts(arguments: Mapping[str, object], key: str) -> tuple[str, ...]:
    """A list of strings; empty when it is left out."""
    value = arguments.get(key)
    if value is None:
        return ()
    items: Any = value
    if not isinstance(value, list) or not all(isinstance(i, str) and i.strip() for i in list[object](items)):
        raise ValueError(f"{key} is a list of strings")
    return tuple(str(i).strip() for i in list[object](items))


def mapping(arguments: Mapping[str, object], key: str) -> dict[str, Any]:
    """An object argument, given as an object or as JSON text of one (a provider that cannot take an object whose fields
    the schema does not name is offered text); empty when it is left out."""
    value = arguments.get(key)
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else None
        except ValueError as e:
            raise ValueError(f"{key} is a JSON object") from e
    if value is None:
        return {}
    loose: Any = value
    if not isinstance(value, dict):
        raise ValueError(f"{key} is an object")
    return {str(k): v for k, v in dict[object, object](loose).items()}


def number(arguments: Mapping[str, object], key: str, default: int, most: int) -> int:
    """A whole number from 1 to `most`; `default` when it is left out."""
    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= most:
        raise ValueError(f"{key} is a whole number from 1 to {most}")
    return value
