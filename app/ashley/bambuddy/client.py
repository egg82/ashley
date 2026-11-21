"""The port to Bambuddy's REST API (`ashley.services`): a GET, a JSON POST or a file upload under a base URL with an API
key, answering the parsed JSON body. The key travels in the `X-API-Key` header (the OpenAPI's bearer scheme is for the login token) and is never logged or put in an exception message; a call
logs `bambuddy.get`, `bambuddy.post` or `bambuddy.upload` with the endpoint's path (no query), the status and duration_ms."""

import logging
import time
from abc import abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

import httpx2

from .. import logs
from ..connections import address
from ..services import Service

log = logging.getLogger("ashley.bambuddy")
_SCHEMES = frozenset({"http", "https"})
_REJECTED = frozenset({400, 409, 413, 415, 422})


Reason = Literal["refused", "unreachable", "not_bambuddy", "not_found", "rejected"]
"""Why a call failed: `refused`, Bambuddy turned the key away (401, 403, a key without the permission the read needs
included); `unreachable`, no answer, a timeout, a redirect, or a server error; `not_bambuddy`, what answered is not
Bambuddy's API (a body that is not its JSON); `not_found`, a 404, which for a path naming one record is Bambuddy's answer
for a record it does not have; `rejected`, a write Bambuddy turned away as wrong (400, 409, 413, 415, 422), which a
read never answers."""


class BambuddyFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


def base_url(text: str) -> str | None:
    """`text` as a Bambuddy base URL (`https://prints.example`, a path allowed for an app served under one, no trailing
    slash), or None when it is not http or https, has no host, or carries credentials, a query or a fragment."""
    return address.base_url(text, _SCHEMES)


class Bambuddy(Service):
    @classmethod
    def null(cls) -> "Bambuddy":
        return NullBambuddy()

    @abstractmethod
    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int | bool]) -> object:
        """The parsed JSON of `GET {base}{path}?{params}`, `path` starting `/api/v1/`. Raises BambuddyFailed."""

    @abstractmethod
    async def post(self, base: str, api_key: str, path: str, body: Mapping[str, object]) -> object:
        """The parsed JSON of `POST {base}{path}` with `body` as JSON. Raises BambuddyFailed."""

    @abstractmethod
    async def upload(self, base: str, api_key: str, path: str, name: str, data: bytes) -> object:
        """The parsed JSON of `POST {base}{path}` with the file `name` of `data` as multipart form field `file`, allowed
        the longer upload timeout. Raises BambuddyFailed."""


class NullBambuddy(Bambuddy):
    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int | bool]) -> object:
        raise BambuddyFailed("unreachable")

    async def post(self, base: str, api_key: str, path: str, body: Mapping[str, object]) -> object:
        raise BambuddyFailed("unreachable")

    async def upload(self, base: str, api_key: str, path: str, name: str, data: bytes) -> object:
        raise BambuddyFailed("unreachable")


class HttpBambuddy(Bambuddy):
    def __init__(self, http: httpx2.AsyncClient, timeout_s: float, upload_timeout_s: float) -> None:
        """`http` must not follow redirects: a redirect would carry the key to wherever it points."""
        self._http = http
        self._timeout_s = timeout_s
        self._upload_timeout_s = upload_timeout_s

    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int | bool]) -> object:
        query = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        return await self._send("get", path, lambda: self._http.get(
            base + path, params=query, timeout=self._timeout_s, headers=_headers(api_key)))

    async def post(self, base: str, api_key: str, path: str, body: Mapping[str, object]) -> object:
        return await self._send("post", path, lambda: self._http.post(
            base + path, json=body, timeout=self._timeout_s, headers=_headers(api_key)))

    async def upload(self, base: str, api_key: str, path: str, name: str, data: bytes) -> object:
        return await self._send("upload", path, lambda: self._http.post(
            base + path, files={"file": (name, data, "application/octet-stream")}, timeout=self._upload_timeout_s,
            headers=_headers(api_key)))

    async def _send(self, how: str, path: str,
                    request: Callable[[], Awaitable[httpx2.Response]]) -> object:
        started = time.monotonic()
        try:
            response = await request()
        except httpx2.HTTPError as e:
            _logged(how, path, "none", started)
            raise BambuddyFailed("unreachable") from e
        _logged(how, path, response.status_code, started)
        if response.status_code in (401, 403):
            raise BambuddyFailed("refused")
        if response.status_code == 404:
            raise BambuddyFailed("not_found")
        if how != "get" and response.status_code in _REJECTED:
            raise BambuddyFailed("rejected")
        if not response.is_success:
            raise BambuddyFailed("unreachable")
        try:
            return response.json()
        except ValueError as e:
            raise BambuddyFailed("not_bambuddy") from e


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Accept": "application/json"}


def _logged(how: str, path: str, status: int | str, started: float) -> None:
    logs.info(log, f"bambuddy.{how}", path=path, status=status, duration_ms=int((time.monotonic() - started) * 1000))
