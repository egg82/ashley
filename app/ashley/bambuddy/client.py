"""The port to Bambuddy's REST API (`ashley.services`): a GET under a base URL with an API key, answering the parsed JSON
body. The key travels in the `X-API-Key` header (the OpenAPI's bearer scheme is for the login token) and is never logged or put in an exception message; a call
logs `bambuddy.get` with the endpoint's path (no query), the status and duration_ms."""

import logging
import time
from abc import abstractmethod
from collections.abc import Mapping
from typing import Literal

import httpx2

from .. import logs
from ..connections import address
from ..services import Service

log = logging.getLogger("ashley.bambuddy")
_SCHEMES = frozenset({"http", "https"})


Reason = Literal["refused", "unreachable", "not_bambuddy", "not_found"]
"""Why a call failed: `refused`, Bambuddy turned the key away (401, 403, a key without the permission the read needs
included); `unreachable`, no answer, a timeout, a redirect, or a server error; `not_bambuddy`, what answered is not
Bambuddy's API (a body that is not its JSON); `not_found`, a 404, which for a path naming one record is Bambuddy's answer
for a record it does not have."""


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


class NullBambuddy(Bambuddy):
    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int | bool]) -> object:
        raise BambuddyFailed("unreachable")


class HttpBambuddy(Bambuddy):
    def __init__(self, http: httpx2.AsyncClient, timeout_s: float) -> None:
        """`http` must not follow redirects: a redirect would carry the key to wherever it points."""
        self._http = http
        self._timeout_s = timeout_s

    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int | bool]) -> object:
        started = time.monotonic()
        query = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        try:
            response = await self._http.get(base + path, params=query, timeout=self._timeout_s,
                                            headers={"X-API-Key": api_key, "Accept": "application/json"})
        except httpx2.HTTPError as e:
            _logged(path, "none", started)
            raise BambuddyFailed("unreachable") from e
        _logged(path, response.status_code, started)
        if response.status_code in (401, 403):
            raise BambuddyFailed("refused")
        if response.status_code == 404:
            raise BambuddyFailed("not_found")
        if not response.is_success:
            raise BambuddyFailed("unreachable")
        try:
            return response.json()
        except ValueError as e:
            raise BambuddyFailed("not_bambuddy") from e


def _logged(path: str, status: int | str, started: float) -> None:
    logs.info(log, "bambuddy.get", path=path, status=status, duration_ms=int((time.monotonic() - started) * 1000))
