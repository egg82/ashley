"""Typed reads from parsed JSON. The parameters are `Any` because that is what `json.loads` returns, and each
function narrows to a type the checker can follow."""

from typing import Any


def obj(value: Any) -> dict[str, object]:
    # `__class__ is` rather than isinstance: isinstance would narrow `value` to dict[Unknown, Unknown], which strict
    # mode rejects.
    return {k: v for k, v in value.items() if isinstance(k, str)} if value.__class__ is dict else {}


def items(value: Any) -> list[dict[str, object]]:
    return [obj(v) for v in value] if value.__class__ is list else []


def strings(value: Any) -> list[str] | None:
    """The list of strings `value` is, or None for anything else (including a list holding a non-string)."""
    return [*value] if value.__class__ is list and all(isinstance(v, str) for v in value) else None


def text(d: dict[str, object], key: str) -> str | None:
    v = d.get(key)
    return v if isinstance(v, str) and v != "" else None


def integer(d: dict[str, object], key: str) -> int | None:
    v = d.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None
