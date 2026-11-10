"""Pieces of the HA websocket-answered blind tests: a stand-in Home Assistant on a real local port (its WebSocket API and
the few REST paths a read needs), the real Postgres-backed Connections, and a count of writes to the connections table."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import AsyncGenerator, Coroutine, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

import httpx2
import psycopg
import pytest
import uvicorn
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant import house_settings
from ashley.home_assistant.house_settings import HouseSettings
from ashley.home_assistant.rest_automations import AutomationsConfig
from ashley.wiring import CONNECTION_KINDS
from contract.conversations_support import scalar
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from connection_legacy_support import put_of

T = TypeVar("T")
Json = dict[str, Any]

TOKEN = "ha-token-0001-SECRETKEY"
HA_CONFIG = AutomationsConfig(timeout_s=2.0, entity_tries=1, entity_wait_s=0.0)
KEY = os.urandom(32)


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


# --- the stand-in -----------------------------------------------------------------------------------------------------


@dataclass
class Ha:
    """The stand-in's state and what it saw. A command whose `type` starts `reject/` is answered with an error of
    Home Assistant's own; any other is answered with success, a list for a `.../list` and an echo of its fields else."""

    url: str = ""
    token: str = TOKEN
    auth_ok: bool = True
    drop: bool = False
    garbage: bool = False
    event: bool = False
    shapeless: bool = False
    stubborn: bool = False
    mute: bool = False
    commands: list[Json] = field(default_factory=lambda: [])
    ws_ok: int = 0
    rest_ok: int = 0
    connections: int = 0

    def reset(self) -> None:
        self.token, self.auth_ok, self.drop, self.garbage, self.event = TOKEN, True, False, False, False
        self.shapeless = self.stubborn = self.mute = False
        self.commands, self.ws_ok, self.rest_ok, self.connections = [], 0, 0, 0


def _answer(ha: Ha, command: Json) -> Json:
    kind = str(command["type"])
    if kind.startswith("reject/"):
        return {"success": False, "error": {"code": "invalid_format", "message": "extra keys not allowed"}}
    if kind.startswith("odd/"):
        return {"success": False, "error": {"code": "odd_code", "message": "something odd"}}
    ha.ws_ok += 1
    if kind.endswith("/list"):
        return {"success": True, "result": []}
    fields = {k: v for k, v in command.items() if k not in ("id", "type")}
    name = str(fields.get("name", "x"))
    return {"success": True, "result": {**fields, "area_id": name, "floor_id": name, "label_id": name, "id": name}}


async def _websocket(ha: Ha, socket: WebSocket) -> None:
    await socket.accept()
    ha.connections += 1
    if ha.drop:
        await socket.close()
        return
    await socket.send_json({"type": "hello" if ha.mute else "auth_required", "ha_version": "2026.10.4"})
    try:
        auth = await socket.receive_json()
        if auth.get("access_token") != ha.token or not ha.auth_ok:
            await socket.send_json({"type": "auth_invalid", "message": "Invalid access token or password"})
            if not ha.stubborn:
                await socket.close()
                return
        if not ha.stubborn or ha.auth_ok and auth.get("access_token") == ha.token:
            await socket.send_json({"type": "auth_ok", "ha_version": "2026.10.4"})
        while True:
            command = await socket.receive_json()
            ha.commands.append({k: v for k, v in command.items() if k != "id"})
            if ha.garbage:
                await socket.send_text("this is not json")
                continue
            if ha.shapeless:
                await socket.send_json({"id": command["id"], "type": "result"})
                continue
            if ha.event:
                await socket.send_json({"id": command["id"], "type": "event", **_answer(ha, command)})
                continue
            await socket.send_json({"id": command["id"], "type": "result", **_answer(ha, command)})
    except WebSocketDisconnect:
        return


async def _api(ha: Ha, request: Request) -> JSONResponse:
    if request.headers.get("authorization") != f"Bearer {ha.token}":
        return JSONResponse({"message": "401: Unauthorized"}, status_code=401)
    ha.rest_ok += 1
    return JSONResponse({"message": "API running."})


def _app(ha: Ha) -> Starlette:
    async def api(request: Request) -> JSONResponse:
        return await _api(ha, request)

    async def socket(websocket: WebSocket) -> None:
        await _websocket(ha, websocket)

    async def text(request: Request) -> PlainTextResponse:
        ha.rest_ok += 1
        return PlainTextResponse("API running.")

    return Starlette(routes=[Route("/api/", api), Route("/api/text", text), WebSocketRoute("/api/websocket", socket)])


class Server:
    def __init__(self, ha: Ha) -> None:
        self.ha = ha
        config = uvicorn.Config(_app(ha), host="127.0.0.1", port=0, ws="wsproto", lifespan="off", log_config=None)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve()), daemon=True)

    def start(self) -> None:
        self.thread.start()
        for _ in range(500):
            if self.server.started and self.server.servers:
                break
            threading.Event().wait(0.01)
        assert self.server.started, "the stand-in did not start"
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.ha.url = f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture(scope="session")
def stand_in() -> Generator[Ha]:
    ha = Ha()
    server = Server(ha)
    server.start()
    yield ha
    server.stop()


@pytest.fixture
def ha(stand_in: Ha) -> Generator[Ha]:
    stand_in.reset()
    yield stand_in
    stand_in.reset()


def client_for(base_url: str, token: str = TOKEN, answered: Any = None) -> HomeAssistant:
    http = httpx2.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {token}"})
    return HomeAssistant(http) if answered is None else HomeAssistant(http, answered)


def settings() -> HouseSettings:
    return house_settings.load()


class Counter:
    """An `answered` callback that counts its awaits."""

    def __init__(self) -> None:
        self.n = 0

    async def __call__(self) -> None:
        self.n += 1


# --- the database ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    url: str
    home: int
    other: int
    alana: int
    kim: int


def make_world(url: str) -> World:
    home = scalar(url, "INSERT INTO households (name) VALUES ('home') RETURNING id")
    other = scalar(url, "INSERT INTO households (name) VALUES ('other') RETURNING id")
    alana = scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Alana') RETURNING id", (home,))
    kim = scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'Kim') RETURNING id", (other,))
    return World(url, int(home), int(other), int(alana), int(kim))


@asynccontextmanager
async def connections(url: str) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url)
    await database.open()
    service = PostgresConnections(database, Sealer({1: KEY}, current=1))
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    services.register(Connections, service)
    try:
        yield service
    finally:
        await database.close()


async def hold(c: Connections, who: World, household: int) -> int:
    """Store the household's Home Assistant connection, as a checked PUT would, returning its id."""
    made = await put_of(c, household, "home_assistant", "http://ha.test:8123", TOKEN, who.alana if household == who.home else who.kim)
    return made.id


def homes(c: Connections, ha: Ha) -> ConnectedHomes:
    """Real ConnectedHomes whose clients reach the stand-in, whatever address the connection stores."""
    def connect(base_url: str, token: str) -> HomeAssistant:
        return HomeAssistant(httpx2.AsyncClient(base_url=ha.url, headers={"Authorization": f"Bearer {token}"}))

    return ConnectedHomes(c, HA_CONFIG, connect)


def stored_at(url: str, household: int) -> datetime:
    return scalar(url, "SELECT checked_at FROM connections WHERE household_id = %s AND kind = 'home_assistant'", (household,))


def age(url: str, household: int) -> datetime:
    """Move the stored connection's `checked_at` an hour into the past and return it, so a later move is unmistakable."""
    return scalar(url, "UPDATE connections SET checked_at = checked_at - interval '1 hour' WHERE household_id = %s "
                       "AND kind = 'home_assistant' RETURNING checked_at", (household,))


def count_writes(url: str) -> None:
    """From now on every update of a connections row bumps `hwa_writes.n`."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE TABLE hwa_writes (n int NOT NULL)")
        conn.execute("INSERT INTO hwa_writes VALUES (0)")
        conn.execute("CREATE FUNCTION hwa_bump() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                     "UPDATE hwa_writes SET n = n + 1; RETURN NEW; END $$")
        conn.execute("CREATE TRIGGER hwa_count AFTER UPDATE ON connections FOR EACH ROW EXECUTE FUNCTION hwa_bump()")


def writes(url: str) -> int:
    return int(scalar(url, "SELECT n FROM hwa_writes"))


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''}" for r in caplog.records)


def all_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
