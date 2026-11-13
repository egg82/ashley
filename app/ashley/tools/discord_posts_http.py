"""`ChannelPosts` over Discord's REST API: `GET /channels/<id>/messages?limit=<n>` with `Authorization: Bot <token>`.
The token is asked for on each read, so one replaced in the room is used at once, and is never logged."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
from pydantic import TypeAdapter, ValidationError

from ..connections.connections import ConnectionsUnavailable
from .discord_posts import ChannelPosts, Post, PostsFailed

API = "https://discord.com/api/v10"
_MESSAGES = TypeAdapter(list[dict[str, Any]])


class HttpChannelPosts(ChannelPosts):
    """`token` gives the bot's token, empty when there is none. `api` is Discord's REST root."""

    def __init__(self, token: Callable[[], Awaitable[str]], http: httpx2.AsyncClient, api: str = API) -> None:
        self._token = token
        self._http = http
        self._api = api

    async def recent(self, channel_id: int, count: int) -> list[Post]:
        try:
            token = await self._token()
        except ConnectionsUnavailable as e:
            raise PostsFailed("no_token") from e
        if not token:
            raise PostsFailed("no_token")
        try:
            got = await self._http.get(f"{self._api}/channels/{channel_id}/messages", params={"limit": count},
                                       headers={"Authorization": f"Bot {token}"})
        except httpx2.HTTPError as e:
            raise PostsFailed("unreachable") from e
        if got.status_code in (401, 403):
            raise PostsFailed("refused")
        if got.status_code == 404:
            raise PostsFailed("not_found")
        if got.status_code != 200:
            raise PostsFailed("unreachable" if got.status_code == 429 or got.status_code >= 500 else "unexpected")
        try:
            raw = _MESSAGES.validate_json(got.content)
            return [_post(m) for m in reversed(raw)][-count:]
        except (ValidationError, KeyError, ValueError, TypeError) as e:
            raise PostsFailed("unexpected") from e


def _post(m: dict[str, Any]) -> Post:
    author = m["author"]
    name = author.get("global_name") or author["username"]
    return Post(int(m["id"]), str(name), bool(author.get("bot", False)), str(m["timestamp"]), str(m.get("content") or ""))
