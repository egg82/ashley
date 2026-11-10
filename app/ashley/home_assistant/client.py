"""One Home Assistant instance as a configured `httpx2.AsyncClient`: its base URL and a long-lived access token sent
as a bearer header. The token is never logged and never appears in an exception message."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2


async def _unrecorded() -> None:
    return None


@dataclass(frozen=True)
class HomeAssistant:
    """`http` has `base_url` set to the instance (`http://homeassistant.local:8123`) and the `Authorization` header set;
    callers pass paths (`/api/mcp/assist`, `/api/states/person.alana`). `answered` is awaited once per WebSocket command
    Home Assistant answered successfully; it records nothing unless the client was made for a stored connection."""

    http: httpx2.AsyncClient
    answered: Callable[[], Awaitable[None]] = _unrecorded


def connect(base_url: str, token: str) -> HomeAssistant:
    return HomeAssistant(httpx2.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {token}"}))
