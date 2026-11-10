"""One capped, streamed GET for the forge adapters, and its one log line (`codehost.get`: forge, call, project, status,
bytes, duration_ms; never the token, a path's text or a URL). A redirect is followed only where the caller says so
(an archive's signed download address), then without the token."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx2

from .. import logs
from .host import CodeHostFailed
from .model import Access

log = logging.getLogger("ashley.codehost")
JSON_MAX = 4 * 1024 * 1024
Call = Literal["check", "projects", "tree", "file", "archive"]


@dataclass(frozen=True)
class Got:
    body: bytes
    cut: bool
    next: bool
    """Whether the host says a further page exists."""
    json: bool
    """Whether the host answered with a JSON document (GitHub answers a directory with its listing whatever media type
    was asked for)."""


class Wire:
    def __init__(self, http: httpx2.AsyncClient, timeout_s: float) -> None:
        """`http` must not follow redirects: one would carry the token to wherever it points."""
        self._http = http
        self._timeout_s = timeout_s

    async def get(self, access: Access, call: Call, project: str, url: str, params: dict[str, str | int],
                  headers: dict[str, str], cap: int, redirect: bool = False) -> Got:
        """Raises CodeHostFailed."""
        started = time.monotonic()
        status: int | str = "none"
        size = 0
        try:
            response, body, cut = await self._once(url, params, headers, cap)
            status = response.status_code
            if redirect and 300 <= status < 400:
                response, body, cut = await self._follow(response, cap)
                status = response.status_code
            size = len(body)
            self._judge(response, cut and call == "archive")
            next_page = bool(response.headers.get("x-next-page")) or 'rel="next"' in response.headers.get("link", "")
            return Got(body, cut, next_page, response.headers.get("content-type", "").startswith("application/json"))
        except httpx2.HTTPError as e:
            raise CodeHostFailed("unreachable") from e
        finally:
            logs.info(log, "codehost.get", forge=access.forge, call=call, project=project, status=status, bytes=size,
                      duration_ms=int((time.monotonic() - started) * 1000))

    async def _follow(self, redirected: httpx2.Response, cap: int) -> tuple[httpx2.Response, bytes, bool]:
        target = redirected.headers.get("location", "")
        if not target.startswith("https://"):
            raise CodeHostFailed("unexpected")
        return await self._once(target, {}, {}, cap)

    async def _once(self, url: str, params: dict[str, str | int], headers: dict[str, str],
                    cap: int) -> tuple[httpx2.Response, bytes, bool]:
        async with self._http.stream("GET", url, params=params, headers=headers, timeout=self._timeout_s) as response:
            if not response.is_success:
                return response, b"", False
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > cap:
                    break
            body = b"".join(chunks)
            return response, body[:cap], len(body) > cap

    @staticmethod
    def _judge(response: httpx2.Response, too_large: bool) -> None:
        if response.status_code in (401, 403):
            raise CodeHostFailed("refused")
        if response.status_code == 404:
            raise CodeHostFailed("not_found")
        if not response.is_success:
            raise CodeHostFailed("unreachable")
        if too_large:
            raise CodeHostFailed("too_large")


def json_rows(body: bytes) -> list[dict[str, Any]]:
    """The objects of a JSON list body. Raises CodeHostFailed (`unexpected`) for any other shape."""
    try:
        parsed: object = json.loads(body)
    except ValueError as e:
        raise CodeHostFailed("unexpected") from e
    loose: Any = parsed
    if not isinstance(parsed, list):
        raise CodeHostFailed("unexpected")
    objects: list[dict[str, Any]] = []
    for row in list[object](loose):
        item: Any = row
        if not isinstance(row, dict):
            raise CodeHostFailed("unexpected")
        objects.append(dict[str, Any](item))
    return objects
