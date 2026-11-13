"""The port to Sure's REST API (`ashley.services`): one GET under a base URL with an API key, answering the parsed JSON
body. Reads only. The key travels in the `X-Api-Key` header and is never logged or put in an exception message; a
call logs `sure.get` with the endpoint's path (no query), the status and duration_ms."""

import logging
import time
from abc import abstractmethod
from collections.abc import Mapping
from typing import Literal

import httpx2

from .. import logs
from ..connections import address
from ..services import Service

log = logging.getLogger("ashley.sure")
_HTTPS = frozenset({"https"})

Reason = Literal["refused", "unreachable", "not_sure"]
"""Why a call failed: `refused`, Sure turned the key away (401, 403); `unreachable`, no answer, a timeout, a redirect,
or a server error; `not_sure`, what answered is not Sure's API (404, or a body that is not its JSON)."""


class SureFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


def base_url(text: str) -> str | None:
    """`text` as a Sure base URL (`https://money.example`, a path allowed for an app served under one, no trailing
    slash), or None when it is not https, has no host, or carries credentials, a query or a fragment."""
    return address.base_url(text, _HTTPS)


class Sure(Service):
    @classmethod
    def null(cls) -> "Sure":
        return NullSure()

    @abstractmethod
    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int]) -> object:
        """The parsed JSON of `GET {base}{path}?{params}`, `path` starting `/api/v1/`. Raises SureFailed."""


class NullSure(Sure):
    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int]) -> object:
        raise SureFailed("unreachable")


class HttpSure(Sure):
    def __init__(self, http: httpx2.AsyncClient, timeout_s: float) -> None:
        """`http` must not follow redirects: a redirect would carry the key to wherever it points."""
        self._http = http
        self._timeout_s = timeout_s

    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int]) -> object:
        return await self._send("get", base, api_key, path, dict(params), None)

    async def _send(self, method: Literal["get"], base: str, api_key: str, path: str,
                    params: dict[str, str | int] | None, body: dict[str, object] | None) -> object:
        started = time.monotonic()
        try:
            response = await self._http.request(method.upper(), base + path, params=params, json=body,
                                                timeout=self._timeout_s,
                                                headers={"X-Api-Key": api_key, "Accept": "application/json"})
        except httpx2.HTTPError as e:
            _logged(method, path, "none", started)
            raise SureFailed("unreachable") from e
        _logged(method, path, response.status_code, started)
        if response.status_code in (401, 403):
            raise SureFailed("refused")
        if response.status_code == 404:
            raise SureFailed("not_sure")
        if not response.is_success:
            raise SureFailed("unreachable")
        try:
            return response.json()
        except ValueError as e:
            raise SureFailed("not_sure") from e


def _logged(method: str, path: str, status: int | str, started: float) -> None:
    logs.info(log, f"sure.{method}", path=path, status=status, duration_ms=int((time.monotonic() - started) * 1000))
