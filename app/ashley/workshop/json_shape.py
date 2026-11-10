"""Parsed JSON read as the shapes the workshop's data files and bodies are in, without a `dict[Unknown, Unknown]`."""

from typing import Any


def object_of(data: object) -> dict[str, object] | None:
    """`data` as a JSON object; None when it is not one."""
    loose: Any = data
    return {str(k): v for k, v in dict[object, object](loose).items()} if isinstance(data, dict) else None


def list_of(data: object) -> list[object] | None:
    """`data` as a JSON array; None when it is not one."""
    loose: Any = data
    return list[object](loose) if isinstance(data, list) else None
