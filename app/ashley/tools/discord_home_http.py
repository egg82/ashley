"""`HomeChannel` over Discord's REST API with `Authorization: Bot <token>`: `GET /users/@me` for whose messages are hers,
`GET /channels/<id>/messages` and `/pins`, `PATCH /channels/<id>` for the topic, `GET /channels/<id>/messages/<m>` then
`PUT` or `DELETE /channels/<id>/pins/<m>`. The token is asked for on each call and never logged."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
from pydantic import TypeAdapter, ValidationError

from ..connections.connections import ConnectionsUnavailable
from .discord_home import HomeChannel, HomeFailed, Mine
from .discord_posts_http import API

_MESSAGES = TypeAdapter(list[dict[str, Any]])
_ONE = TypeAdapter(dict[str, Any])


class HttpHomeChannel(HomeChannel):
    """`token` gives the bot's token, empty when there is none. `api` is Discord's REST root."""

    def __init__(self, token: Callable[[], Awaitable[str]], http: httpx2.AsyncClient, api: str = API) -> None:
        self._token = token
        self._http = http
        self._api = api

    async def mine(self, channel_id: int, count: int) -> list[Mine]:
        token = await self._bot_token()
        me = _id(await self._call(token, "GET", "/users/@me"), "id")
        latest = _many(await self._call(token, "GET", f"/channels/{channel_id}/messages", params={"limit": count}))
        pins = _many(await self._call(token, "GET", f"/channels/{channel_id}/pins"))
        pinned = {_id(m, "id") for m in pins}
        try:
            found = {_id(m, "id"): m for m in [*latest, *pins] if _id(m.get("author"), "id") == me}
            return [Mine(i, str(m["timestamp"]), str(m.get("content") or ""), i in pinned)
                    for i, m in sorted(found.items())]
        except KeyError as e:
            raise HomeFailed("unexpected") from e

    async def set_topic(self, channel_id: int, topic: str) -> None:
        token = await self._bot_token()
        await self._call(token, "PATCH", f"/channels/{channel_id}", json={"topic": topic})

    async def pin(self, channel_id: int, message_id: int, pinned: bool) -> None:
        token = await self._bot_token()
        me = _id(await self._call(token, "GET", "/users/@me"), "id")
        message = await self._call(token, "GET", f"/channels/{channel_id}/messages/{message_id}")
        if _id(_dict(message).get("author"), "id") != me:
            raise HomeFailed("not_hers")
        await self._call(token, "PUT" if pinned else "DELETE", f"/channels/{channel_id}/pins/{message_id}")

    async def _bot_token(self) -> str:
        try:
            token = await self._token()
        except ConnectionsUnavailable as e:
            raise HomeFailed("no_token") from e
        if not token:
            raise HomeFailed("no_token")
        return token

    async def _call(self, token: str, method: str, path: str, **sent: Any) -> Any:
        """The decoded answer, None for 204. Raises HomeFailed by status."""
        try:
            got = await self._http.request(method, f"{self._api}{path}", headers={"Authorization": f"Bot {token}"},
                                           **sent)
        except httpx2.HTTPError as e:
            raise HomeFailed("unreachable") from e
        if got.status_code in (401, 403):
            raise HomeFailed("refused")
        if got.status_code == 404:
            raise HomeFailed("not_found")
        if got.status_code == 429 or got.status_code >= 500:
            raise HomeFailed("unreachable")
        if got.status_code == 204:
            return None
        if got.status_code != 200:
            raise HomeFailed("unexpected")
        try:
            return got.json()
        except ValueError as e:
            raise HomeFailed("unexpected") from e


def _many(raw: Any) -> list[dict[str, Any]]:
    try:
        return _MESSAGES.validate_python(raw)
    except ValidationError as e:
        raise HomeFailed("unexpected") from e


def _dict(raw: Any) -> dict[str, Any]:
    try:
        return _ONE.validate_python(raw)
    except ValidationError as e:
        raise HomeFailed("unexpected") from e


def _id(raw: Any, key: str) -> int:
    try:
        return int(_dict(raw)[key])
    except (KeyError, ValueError, TypeError) as e:
        raise HomeFailed("unexpected") from e
