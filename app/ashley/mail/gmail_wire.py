"""One capped GET or POST of Gmail's REST API (https://developers.google.com/workspace/gmail/api/reference/rest) as
JSON, with the access token as a bearer. A redirect is not followed, so the token goes only where it was sent. A POST is
made once, never retried."""

import json
from collections.abc import Mapping
from typing import Any

import httpx2
from pydantic import BaseModel, ValidationError

from .model import MailFailed

API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailWire:
    def __init__(self, http: httpx2.AsyncClient, timeout_s: float, cap_bytes: int) -> None:
        """`http` must not follow redirects."""
        self._http = http
        self._timeout_s = timeout_s
        self._cap = cap_bytes

    async def get[S: BaseModel](self, token: str, path: str, params: dict[str, str | int | list[str]],
                                shape: type[S]) -> S:
        """`path` under the signed-in user's mailbox, answered as `shape`. Raises MailFailed: `refused` for 401 and 403,
        `not_found` for 400 and 404 (Gmail answers 400 to an id it does not recognise), `unreachable` for anything
        else, including an answer that is not `shape` or is over the cap."""
        return await self._send(token, "GET", path, params, None, shape)

    async def post[S: BaseModel](self, token: str, path: str, body: Mapping[str, object], shape: type[S]) -> S:
        """`body` as JSON to `path`, answered as `shape` (an empty answer is `{}`). Raises MailFailed: `refused` for
        400, 401 and 403 (the call was turned away), `not_found` for 404, `unreachable` for anything else, an answer
        that is not `shape` and a call that timed out, which leaves open whether it took effect."""
        return await self._send(token, "POST", path, {}, body, shape)

    async def _send[S: BaseModel](self, token: str, method: str, path: str, params: dict[str, str | int | list[str]],
                                  body: Mapping[str, object] | None, shape: type[S]) -> S:
        try:
            async with self._http.stream(method, API + path, params=params, timeout=self._timeout_s, json=body,
                                         headers={"authorization": f"Bearer {token}", "accept": "application/json"}) as r:
                _judge(r.status_code, method)
                answer = await _capped(r, self._cap)
        except httpx2.HTTPError as e:
            raise MailFailed("unreachable") from e
        return _shaped(answer or b"{}" if method == "POST" else answer, shape)


def _judge(status: int, method: str = "GET") -> None:
    if status in (401, 403) or (status == 400 and method == "POST"):
        raise MailFailed("refused")
    if status in (400, 404):
        raise MailFailed("not_found")
    if not 200 <= status < 300:
        raise MailFailed("unreachable")


async def _capped(response: httpx2.Response, cap: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size > cap:
            raise MailFailed("unreachable")
    return b"".join(chunks)


def _shaped[S: BaseModel](body: bytes, shape: type[S]) -> S:
    try:
        parsed: Any = json.loads(body)
        return shape.model_validate(parsed)
    except (ValueError, ValidationError) as e:
        raise MailFailed("unreachable") from e
