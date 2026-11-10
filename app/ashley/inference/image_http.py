"""What the image providers share on the wire: one JSON POST whose every transport failure is a `ProviderFailed`, and
the reads of untyped JSON."""

from typing import Any

import httpx2

from .provider import ProviderFailed


async def post_json(client: httpx2.AsyncClient, path: str, body: dict[str, object],
                    timeout_s: float) -> tuple[int, object]:
    """The status and parsed JSON body (None when the body is not JSON) of a POST. Raises ProviderFailed:
    `unavailable` for a timeout or a connection failure, `error` for anything else unexpected."""
    try:
        response = await client.post(path, json=body, timeout=timeout_s)
    except httpx2.HTTPError as e:
        raise ProviderFailed("unavailable", type(e).__name__) from e
    except Exception as e:
        raise ProviderFailed("error", type(e).__name__) from e
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def obj(value: object) -> dict[str, object] | None:
    """`value` as a JSON object, None when it is not one."""
    raw: Any = value
    return dict[str, object](raw) if isinstance(value, dict) else None


def items(value: object) -> list[object]:
    """The items of a JSON array, empty when `value` is not one."""
    raw: Any = value
    return list[object](raw) if isinstance(value, list) else []


def count(value: object) -> int:
    """A token count: a whole number, else 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
