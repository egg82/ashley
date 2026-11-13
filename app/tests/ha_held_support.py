"""A stand-in Home Assistant for the held-states tests, served in-process over httpx2's ASGI WebSocket transport: the
WebSocket API's greeting and token, `subscribe_trigger` on a state trigger, `unsubscribe_events` and `get_states`, and
REST's `/api/states/<entity>`. The test changes a thing's state (`change`), which tells every subscription on it as Home
Assistant does, and drops every open socket (`drop`). Names and hosts are made up."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.ha_held_socket import HeldSettings
from ashley.home_assistant.homes import Home, HomeAssistantFailed, Homes
from ashley.home_assistant.house import NullHouse
from httpx2.websockets import ASGIWebSocketTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

SETTINGS = HeldSettings(backoff_s=1, max_backoff_s=8, idle_s=100, ping_s=30)


@dataclass
class Naps:
    """The backoff's sleep: records each delay, then waits until `free` lets it return (each nap uses one)."""

    taken: list[float] = field(default_factory=list[float])
    free: int = 0

    async def __call__(self, seconds: float) -> None:
        self.taken.append(seconds)
        while not self.free:
            await asyncio.sleep(0)
        self.free -= 1


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


TOKEN = "made-up-token-0001"
BASE = "http://ha.example.test"
Json = dict[str, Any]


@dataclass
class Open:
    """One socket the stand-in holds: its subscriptions, by id, on entity ids."""

    socket: WebSocket
    subscriptions: dict[int, str] = field(default_factory=dict[int, str])


@dataclass
class FakeHa:
    states: dict[str, str] = field(default_factory=dict[str, str])
    names: dict[str, str] = field(default_factory=dict[str, str])
    refuse: bool = False
    open: list[Open] = field(default_factory=list[Open])
    commands: list[Json] = field(default_factory=list[Json])
    connections: int = 0
    rest: int = 0

    def state(self, entity: str) -> Json | None:
        if entity not in self.states:
            return None
        return {"entity_id": entity, "state": self.states[entity],
                "attributes": {"friendly_name": self.names.get(entity, entity)}}

    async def change(self, entity: str, to: str | None) -> None:
        """Set the thing's state (None removes it) and tell each subscription on it."""
        before = self.state(entity)
        if to is None:
            self.states.pop(entity, None)
        else:
            self.states[entity] = to
        after = self.state(entity)
        for held in list(self.open):
            for number, watched in held.subscriptions.items():
                if watched == entity:
                    trigger = {"platform": "state", "entity_id": entity, "from_state": before, "to_state": after}
                    await held.socket.send_json({"id": number, "type": "event",
                                                 "event": {"variables": {"trigger": trigger}, "context": None}})

    async def drop(self) -> None:
        for held in list(self.open):
            await held.socket.close()
        self.open.clear()

    def subscribed(self) -> list[str]:
        return sorted(e for held in self.open for e in held.subscriptions.values())

    async def serve(self, socket: WebSocket) -> None:
        await socket.accept()
        self.connections += 1
        await socket.send_json({"type": "auth_required", "ha_version": "2026.10.4"})
        try:
            auth = await socket.receive_json()
            if self.refuse or auth.get("access_token") != TOKEN:
                await socket.send_json({"type": "auth_invalid", "message": "Invalid access token or password"})
                await socket.close()
                return
            await socket.send_json({"type": "auth_ok", "ha_version": "2026.10.4"})
            held = Open(socket)
            self.open.append(held)
            while True:
                command = await socket.receive_json()
                self.commands.append(command)
                await socket.send_json(self._answer(held, command))
        except (WebSocketDisconnect, RuntimeError):
            return

    def _answer(self, held: Open, command: Json) -> Json:
        number, kind = command["id"], command["type"]
        if kind == "subscribe_trigger":
            held.subscriptions[number] = command["trigger"]["entity_id"]
            return {"id": number, "type": "result", "success": True, "result": None}
        if kind == "unsubscribe_events":
            gone = held.subscriptions.pop(command["subscription"], None)
            if gone is None:
                return {"id": number, "type": "result", "success": False, "error": {"code": "not_found", "message": "x"}}
            return {"id": number, "type": "result", "success": True, "result": None}
        if kind == "get_states":
            return {"id": number, "type": "result", "success": True,
                    "result": [self.state(e) for e in sorted(self.states)]}
        return {"id": number, "type": "result", "success": False, "error": {"code": "unknown_command", "message": "x"}}

    def app(self) -> Starlette:
        async def state(request: Request) -> JSONResponse:
            self.rest += 1
            if request.headers.get("authorization") != f"Bearer {TOKEN}":
                return JSONResponse({"message": "401: Unauthorized"}, status_code=401)
            found = self.state(request.path_params["entity"])
            return JSONResponse(found or {"message": "Entity not found."}, status_code=200 if found else 404)

        return Starlette(routes=[Route("/api/states/{entity}", state), WebSocketRoute("/api/websocket", self.serve)])


@dataclass
class FakeHomes(Homes):
    """Household `household`'s house is `home`; any other household has none. Setting `home` to another Home is a person
    replacing the connection."""

    home: Home | None = None
    household: int = 1

    async def of(self, household_id: int) -> Home | None:
        return self.home if household_id == self.household else None

    async def check(self, base_url: str, token: str) -> None:
        raise HomeAssistantFailed("unreachable")


@asynccontextmanager
async def home_of(ha: FakeHa) -> AsyncGenerator[Home]:
    """Household 1's Home over the stand-in, for as long as the block runs."""
    transport = ASGIWebSocketTransport(ha.app())
    async with httpx2.AsyncClient(transport=transport, base_url=BASE,
                                  headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        yield Home(1, HomeAssistant(http), NullHouse())


async def until(condition: Any, what: str, tries: int = 400) -> None:
    """Let the loop run until `condition()` holds; fails naming `what` after `tries` turns of it."""
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never: {what}")
