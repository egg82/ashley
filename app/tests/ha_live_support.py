"""A stand-in Home Assistant WebSocket API on a real local port for the camera WebRTC commands, answering in the shapes
of Home Assistant's own `camera/webrtc.py` (core) and `src/data/camera.ts` (frontend), with made-up values: the
client configuration, an offer answered with a result and then a stream of session, answer and candidate events that stays
open until the client closes, a candidate, and the error a camera without WebRTC gets."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Generator
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx2
import pytest
import uvicorn
from ashley.home_assistant import house_settings
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.house_settings import HouseSettings
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

T = TypeVar("T")
Json = dict[str, Any]
TOKEN = "zq-ha-token-4417"
CAMERA, PLAIN = "camera.zq_porch", "camera.zq_plain"
SESSION = "01ZQSESSION"
ANSWER_SDP = "v=0\r\no=- 1 1 IN IP4 192.0.2.1\r\n"
REMOTE = {"candidate": "candidate:1 1 udp 2113937151 192.0.2.7 50000 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
NO_WEBRTC = "Camera does not support WebRTC, frontend_stream_types=<StreamType.HLS: 'hls'>"


@dataclass
class Ha:
    url: str = ""
    commands: list[Json] = field(default_factory=lambda: [])
    open_streams: int = 0
    closed_streams: int = 0

    def reset(self) -> None:
        self.commands, self.open_streams, self.closed_streams = [], 0, 0


def _error(command: Json, code: str) -> Json:
    return {"id": command["id"], "type": "result", "success": False, "error": {"code": code, "message": NO_WEBRTC}}


def _ok(command: Json, result: Any = None) -> Json:
    return {"id": command["id"], "type": "result", "success": True, "result": result}


def _event(command: Json, event: Json) -> Json:
    return {"id": command["id"], "type": "event", "event": event}


async def _serve(ha: Ha, socket: WebSocket) -> None:
    await socket.accept()
    await socket.send_json({"type": "auth_required", "ha_version": "2026.10.4"})
    try:
        auth = await socket.receive_json()
        if auth.get("access_token") != TOKEN:
            await socket.send_json({"type": "auth_invalid", "message": "Invalid access token or password"})
            return
        await socket.send_json({"type": "auth_ok", "ha_version": "2026.10.4"})
        while True:
            command = await socket.receive_json()
            ha.commands.append({k: v for k, v in command.items() if k != "id"})
            await _answer(ha, socket, command)
    except WebSocketDisconnect:
        return


async def _answer(ha: Ha, socket: WebSocket, command: Json) -> None:
    kind, camera = command["type"], command.get("entity_id")
    if camera == PLAIN and kind.startswith("camera/webrtc/"):
        code = {"camera/webrtc/offer": "webrtc_offer_failed", "camera/webrtc/get_client_config":
                "webrtc_get_client_config_failed", "camera/webrtc/candidate": "webrtc_candidate_failed"}[kind]
        await socket.send_json(_error(command, code))
    elif kind == "camera/webrtc/get_client_config":
        await socket.send_json(_ok(command, {"configuration": {"iceServers": [
            {"urls": ["stun:stun.example.test:3478"]},
            {"urls": "turn:turn.example.test:3478", "username": "zq-user", "credential": "zq-secret"}]},
            "dataChannel": "dataSendChannel"}))
    elif kind == "camera/webrtc/candidate":
        await socket.send_json(_ok(command))
    elif kind == "camera/webrtc/offer":
        ha.open_streams += 1
        await socket.send_json(_ok(command))
        for event in ({"type": "session", "session_id": SESSION}, {"type": "answer", "answer": ANSWER_SDP},
                      {"type": "candidate", "candidate": REMOTE}, {"type": "odd", "x": 1}):
            await socket.send_json(_event(command, event))
        try:
            while True:
                await socket.receive_json()
        finally:
            ha.closed_streams += 1
    else:
        await socket.send_json({"id": command["id"], "type": "result", "success": False,
                                "error": {"code": "unknown_command", "message": "Unknown command."}})


class Server:
    def __init__(self, ha: Ha) -> None:
        async def socket(websocket: WebSocket) -> None:
            await _serve(ha, websocket)

        self.ha = ha
        config = uvicorn.Config(Starlette(routes=[WebSocketRoute("/api/websocket", socket)]), host="127.0.0.1", port=0,
                                ws="wsproto", lifespan="off", log_config=None)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve()), daemon=True)

    def start(self) -> None:
        self.thread.start()
        for _ in range(500):
            if self.server.started and self.server.servers:
                break
            threading.Event().wait(0.01)
        assert self.server.started, "the stand-in did not start"
        self.ha.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"

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


def client_for(url: str, token: str = TOKEN) -> HomeAssistant:
    return HomeAssistant(httpx2.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}))


def settings() -> HouseSettings:
    return house_settings.load()


def go(scenario: Coroutine[Any, Any, T], limit: float = 10.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())
