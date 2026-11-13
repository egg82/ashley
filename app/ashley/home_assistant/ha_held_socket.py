"""One household's held WebSocket to Home Assistant (`ha_held.SocketStates`): a `subscribe_trigger` state trigger on
each thing asked about, and the last state each was told. A dropped socket reconnects with backoff, subscribes every
thing again and reads their states once, so a change while it was down is caught on return.

Logs `ha_held.connected` (household), `ha_held.subscribed` and `ha_held.resubscribed` (household, entities, the
subscriptions now), `ha_held.released` (household, entities let go after `idle_s` unasked) and `ha_held.dropped`
(household, reason, subscriptions, retry_s). Never an entity id, a state, a URL or the token."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from httpx2.websockets import AsyncWebSocketSession, WebSocketDisconnect, WebSocketNetworkError

from .. import logs
from .ha_json import JsonObject, obj, rows, text
from .ha_socket import authenticate, socket_url, token_of
from .held_states import EntityState
from .homes import Home
from .house import HouseUnavailable
from .house_settings import HouseSettings

log = logging.getLogger("ashley.home_assistant")


@dataclass(frozen=True)
class HeldSettings:
    """`backoff_s` before the first reconnect, doubling to `max_backoff_s`; `idle_s` a thing stays subscribed unasked;
    `ping_s` between keepalive pings, and how long one may go unanswered before the socket counts as dropped."""

    backoff_s: float
    max_backoff_s: float
    idle_s: float
    ping_s: float


class Socket:
    def __init__(self, household_id: int, home: Home, settings: HeldSettings, house: HouseSettings,
                 changed: Callable[[], None], sleep: Callable[[float], Awaitable[None]],
                 clock: Callable[[], float]) -> None:
        self.household_id = household_id
        self.home = home
        self._settings, self._house = settings, house
        self._changed, self._sleep, self._clock = changed, sleep, clock
        self._wanted: dict[str, float] = {}
        self._subscribed: dict[str, int] = {}
        self._of: dict[int, str] = {}
        self._known: dict[str, EntityState | None] = {}
        self._waiting: dict[int, asyncio.Future[JsonObject]] = {}
        self._ws: AsyncWebSocketSession | None = None
        self._ready, self._tried = asyncio.Event(), asyncio.Event()
        self._served = self._came_up = False
        self._number = 0
        self._lock = asyncio.Lock()

    async def run(self) -> None:
        """Hold the socket until cancelled. Never raises but CancelledError."""
        delay = self._settings.backoff_s
        while True:
            self._came_up = False
            try:
                await self._session()
                reason = "closed"
            except Exception as e:
                reason = _reason(e)
            if self._came_up:
                delay = self._settings.backoff_s
            logs.warning(log, "ha_held.dropped", household=self.household_id, reason=reason,
                         subscriptions=len(self._wanted), retry_s=delay)
            await self._sleep(delay)
            delay = min(delay * 2, self._settings.max_backoff_s)

    async def states(self, entity_ids: Sequence[str]) -> Mapping[str, EntityState | None]:
        """Each thing as last told, subscribing the ones not yet subscribed. Raises HouseUnavailable while the socket is
        down, or when it has not come up within `timeout_s` of the first ask."""
        now = self._clock()
        for entity in entity_ids:
            self._wanted[entity] = now
        await self._release(now)
        try:
            async with asyncio.timeout(self._house.timeout_s):
                await self._tried.wait()
        except TimeoutError:
            raise HouseUnavailable("websocket: not connected") from None
        if not self._ready.is_set():
            raise HouseUnavailable("websocket: not connected")
        async with self._lock:
            new = [e for e in dict.fromkeys(entity_ids) if e not in self._subscribed]
            if new:
                await self._subscribe(new)
                logs.info(log, "ha_held.subscribed", household=self.household_id, entities=len(new),
                          subscriptions=len(self._subscribed))
        return {e: self._known.get(e) for e in entity_ids}

    async def _session(self) -> None:
        http = self.home.home_assistant.http
        try:
            async with http.websocket(socket_url(http), max_message_size_bytes=self._house.socket_max_bytes,
                                      timeout=self._house.timeout_s, keepalive_ping_interval_seconds=self._settings.ping_s,
                                      keepalive_ping_timeout_seconds=self._settings.ping_s) as ws:
                await authenticate(ws, token_of(http), self._house.timeout_s)
                self._ws = ws
                logs.info(log, "ha_held.connected", household=self.household_id)
                async with asyncio.TaskGroup() as group:
                    group.create_task(self._listen(ws))
                    group.create_task(self._resume())
        finally:
            self._down()

    async def _resume(self) -> None:
        """Subscribe every wanted thing and read their states, then answer asks and tell the holder to look again."""
        async with self._lock:
            entities = sorted(self._wanted)
            await self._subscribe(entities)
        event = "ha_held.resubscribed" if self._served else "ha_held.subscribed"
        self._served = self._came_up = True
        self._ready.set()
        self._tried.set()
        logs.info(log, event, household=self.household_id, entities=len(entities), subscriptions=len(self._subscribed))
        self._changed()

    def _down(self) -> None:
        self._ws = None
        self._ready.clear()
        self._tried.set()
        self._subscribed.clear()
        self._of.clear()
        for future in self._waiting.values():
            if not future.done():
                future.set_exception(HouseUnavailable("websocket: dropped"))
        self._waiting.clear()

    async def _listen(self, ws: AsyncWebSocketSession) -> None:
        while True:
            message = obj(await ws.receive_json())
            number = message.get("id")
            if not isinstance(number, int):
                continue
            if message.get("type") == "result" and number in self._waiting:
                future = self._waiting.pop(number)
                if not future.done():
                    future.set_result(message)
            elif message.get("type") == "event" and number in self._of:
                trigger = obj(obj(obj(message.get("event")).get("variables")).get("trigger"))
                entity = self._of[number]
                self._known[entity] = state_of(entity, trigger.get("to_state"))
                self._changed()

    async def _subscribe(self, entities: Sequence[str]) -> None:
        """A state trigger on each of `entities` (state changes only, not attributes), then their states read once."""
        for entity in entities:
            number = self._next()
            self._of[number] = entity
            try:
                await self._request(number, {"type": "subscribe_trigger",
                                             "trigger": {"platform": "state", "entity_id": entity, "to": None}})
            except BaseException:
                self._of.pop(number, None)
                raise
            self._subscribed[entity] = number
        if entities:
            found = {text(r.get("entity_id")): r for r in rows(await self._request(self._next(), {"type": "get_states"}))}
            for entity in entities:
                self._known[entity] = state_of(entity, found.get(entity))

    async def _release(self, now: float) -> None:
        idle = [e for e, asked in self._wanted.items() if now - asked > self._settings.idle_s]
        if not idle:
            return
        async with self._lock:
            for entity in idle:
                del self._wanted[entity]
                self._known.pop(entity, None)
                number = self._subscribed.pop(entity, None)
                if number is not None:
                    self._of.pop(number, None)
                    try:
                        await self._request(self._next(), {"type": "unsubscribe_events", "subscription": number})
                    except HouseUnavailable:
                        pass
        logs.info(log, "ha_held.released", household=self.household_id, entities=len(idle),
                  subscriptions=len(self._subscribed))

    def _next(self) -> int:
        self._number += 1
        return self._number

    async def _request(self, number: int, command: Mapping[str, object]) -> object:
        """The result of one command on the held socket. Raises HouseUnavailable."""
        ws = self._ws
        if ws is None:
            raise HouseUnavailable("websocket: not connected")
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._waiting[number] = future
        try:
            await ws.send_json({"id": number, **command})
            async with asyncio.timeout(self._house.timeout_s):
                answer = await future
        except (WebSocketDisconnect, WebSocketNetworkError, TimeoutError) as e:
            raise HouseUnavailable(f"websocket: {type(e).__name__}") from e
        finally:
            self._waiting.pop(number, None)
        if answer.get("success") is not True:
            raise HouseUnavailable(f"websocket: {text(obj(answer.get('error')).get('code')) or 'failed'}")
        return answer.get("result")


def state_of(entity: str, raw: object) -> EntityState | None:
    """A state object as Home Assistant sends it; None when there is none (the thing is not in the house)."""
    found = obj(raw)
    if not found:
        return None
    return EntityState(text(found.get("state")), text(obj(found.get("attributes")).get("friendly_name")) or entity)


def _reason(error: BaseException) -> str:
    """What dropped the socket, as a short word: never a message that could carry a URL or a payload."""
    leaf = error
    while (inner := getattr(leaf, "exceptions", None)) and isinstance(first := inner[0], BaseException):
        leaf = first
    if isinstance(leaf, HouseUnavailable):
        return str(leaf).removeprefix("websocket: ")
    return type(leaf).__name__
