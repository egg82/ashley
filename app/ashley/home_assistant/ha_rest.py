"""Home Assistant's REST API for the House adapter: one JSON request, its failure mapped to `HouseRejected` (HA
answered 400 with its own reason) or `HouseUnavailable` (anything else). A failure carries the step and a status or
exception name, never a body or the token."""

import httpx2

from .client import HomeAssistant
from .house import HouseRejected, HouseUnavailable
from .ha_json import obj
from .house_settings import HouseSettings


class Rest:
    def __init__(self, home_assistant: HomeAssistant, settings: HouseSettings) -> None:
        self._http = home_assistant.http
        self._timeout_s = settings.timeout_s

    async def get(self, path: str, step: str, params: dict[str, str] | None = None) -> object:
        """The JSON body of a GET. Raises HouseUnavailable."""
        return _json(await self._send("GET", path, step, None, params), step)

    async def get_or_none(self, path: str, step: str) -> object:
        """As `get`, None for a 404."""
        got = await self._send("GET", path, step, None, None)
        return None if got.status_code == 404 else _json(got, step)

    async def send(self, method: str, path: str, step: str, body: object = None,
                   params: dict[str, str] | None = None) -> object:
        """The JSON body of a POST or DELETE. Raises HouseRejected (HA's 400), HouseUnavailable."""
        got = await self._send(method, path, step, body, params)
        if got.status_code == 400:
            raise HouseRejected(_message(got))
        return _json(got, step)

    async def delete(self, path: str, step: str, missing: tuple[int, ...] = (400, 404)) -> bool:
        """DELETE; False when there was nothing there (a status in `missing`). Raises HouseRejected (HA's 400 when it is
        not `missing`), HouseUnavailable."""
        got = await self._send("DELETE", path, step, None, None)
        if got.status_code in missing:
            return False
        if got.status_code == 400:
            raise HouseRejected(_message(got))
        _json(got, step)
        return True

    async def _send(self, method: str, path: str, step: str, body: object,
                    params: dict[str, str] | None) -> httpx2.Response:
        try:
            return await self._http.request(method, path, json=body, params=params, timeout=self._timeout_s)
        except httpx2.HTTPError as e:
            raise HouseUnavailable(f"{step}: {type(e).__name__}") from e


def _json(got: httpx2.Response, step: str) -> object:
    if got.status_code // 100 != 2:
        raise HouseUnavailable(f"{step}: status {got.status_code}")
    try:
        body: object = got.json()
    except ValueError as e:
        raise HouseUnavailable(f"{step}: not JSON") from e
    return body


def _message(got: httpx2.Response) -> str:
    try:
        raw: object = got.json()
    except ValueError:
        return "Home Assistant refused it"
    message = obj(raw).get("message")
    return message if isinstance(message, str) and message else "Home Assistant refused it"
