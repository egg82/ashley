"""Home Assistant's WebSocket API, one command per connection: connect, authenticate with the client's bearer token,
send the command, read its result, close. No connection outlives a call, so none can go stale between pods or
rollouts. A failure carries a short reason, never a payload, a URL or the token."""

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
import httpx2
from httpx2.websockets import AsyncWebSocketSession, WebSocketDisconnect, WebSocketNetworkError, WebSocketUpgradeError

from .client import HomeAssistant
from .ha_json import obj, text
from .house import HouseRejected, HouseUnavailable
from .house_settings import HouseSettings

_REJECTIONS = frozenset({"invalid_format", "not_found", "home_assistant_error", "service_validation_error",
                         "unknown_error", "invalid_info", "failed", "webrtc_offer_failed",
                         "webrtc_get_client_config_failed", "webrtc_candidate_failed"})


def socket_url(client: httpx2.AsyncClient) -> str:
    """The WebSocket API's address on the client's instance."""
    base = str(client.base_url).rstrip("/")
    scheme = "wss" if base.startswith("https") else "ws"
    return f"{scheme}://{base.split('://', 1)[1]}/api/websocket"


def token_of(client: httpx2.AsyncClient) -> str:
    """The bearer token the client sends."""
    return str(client.headers.get("Authorization", "")).removeprefix("Bearer ")


async def authenticate(ws: AsyncWebSocketSession, token: str, timeout_s: float) -> None:
    """Home Assistant's opening exchange: its greeting, then the token. Raises HouseUnavailable when it does not greet
    or refuses the token."""
    greeting: object = await ws.receive_json(timeout=timeout_s)
    if obj(greeting).get("type") != "auth_required":
        raise HouseUnavailable("websocket: no greeting")
    await ws.send_json({"type": "auth", "access_token": token})
    authenticated: object = await ws.receive_json(timeout=timeout_s)
    if obj(authenticated).get("type") != "auth_ok":
        raise HouseUnavailable("websocket: refused")


class Commands:
    def __init__(self, home_assistant: HomeAssistant, settings: HouseSettings) -> None:
        self._http = home_assistant.http
        self._answered = home_assistant.answered
        self._settings = settings

    async def run(self, command: Mapping[str, object]) -> object:
        """The `result` of the command (a dict with a `type`, as Home Assistant takes it). Raises HouseRejected when Home
        Assistant answers the command with an error of its own (`message` is its text), HouseUnavailable when it cannot be
        reached, refuses the token or answers in a shape this does not read."""
        try:
            async with self._http.websocket(
                    socket_url(self._http), max_message_size_bytes=self._settings.socket_max_bytes,
                    timeout=self._settings.timeout_s, keepalive_ping_interval_seconds=None) as ws:
                await authenticate(ws, token_of(self._http), self._settings.timeout_s)
                await ws.send_json({"id": 1, **command})
                answer: object = await ws.receive_json(timeout=self._settings.timeout_s)
        except BaseExceptionGroup as group:
            raise _unavailable(group) from group
        except (WebSocketDisconnect, WebSocketNetworkError, WebSocketUpgradeError, httpx2.HTTPError, TimeoutError,
                ValueError) as e:
            raise HouseUnavailable(f"websocket: {type(e).__name__}") from e
        result = _result(answer)
        await self._answered()
        return result

    @asynccontextmanager
    async def subscribe(self, command: Mapping[str, object]) -> AsyncGenerator[AsyncIterator[object]]:
        """Send a command Home Assistant answers with a subscription, and yield the `event` of each message it then
        sends under it, until the connection ends. Home Assistant drops the subscription when the connection closes, so
        it stays open exactly as long as this context, which a caller bounds itself: nothing here times a quiet
        subscription out. Entering raises as `run` does; an error after that is the caller's own."""
        started = False
        try:
            async with self._http.websocket(
                    socket_url(self._http), max_message_size_bytes=self._settings.socket_max_bytes,
                    timeout=self._settings.timeout_s, keepalive_ping_interval_seconds=None) as ws:
                await authenticate(ws, token_of(self._http), self._settings.timeout_s)
                await ws.send_json({"id": 1, **command})
                _result(await ws.receive_json(timeout=self._settings.timeout_s))
                started = True
                await self._answered()
                yield _events(ws)
        except BaseExceptionGroup as group:
            if started:
                raise
            raise _unavailable(group) from group
        except (WebSocketDisconnect, WebSocketNetworkError, WebSocketUpgradeError, httpx2.HTTPError, TimeoutError,
                ValueError) as e:
            if started:
                raise
            raise HouseUnavailable(f"websocket: {type(e).__name__}") from e


async def _events(ws: AsyncWebSocketSession) -> AsyncIterator[object]:
    while True:
        try:
            got: object = await ws.receive_json()
        except (WebSocketDisconnect, WebSocketNetworkError):
            return
        message = obj(got)
        if message.get("type") == "event":
            yield message.get("event")


def _unavailable(group: BaseExceptionGroup[BaseException]) -> HouseUnavailable | HouseRejected:
    """The connection's task group wraps what its body raised; the caller sees the one reason inside it."""
    errors, _ = group.split(Exception)
    if errors is None:
        raise group
    leaf = errors.exceptions[0]
    if isinstance(leaf, HouseUnavailable | HouseRejected):
        return leaf
    return HouseUnavailable(f"websocket: {type(leaf).__name__}")


def _result(answer: object) -> object:
    got = obj(answer)
    if got.get("type") != "result":
        raise HouseUnavailable("websocket: not a result")
    if got.get("success") is True:
        return got.get("result")
    error = obj(got.get("error"))
    code, message = text(error.get("code")), text(error.get("message"))
    if code in _REJECTIONS and message:
        raise HouseRejected(message)
    raise HouseUnavailable(f"websocket: {code}")
