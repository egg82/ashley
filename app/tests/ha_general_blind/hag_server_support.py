"""The stand-in Home Assistant as a real server on a local port, one per worker, state reset per test."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Generator
from functools import partial

import pytest
import uvicorn
from hag_rest_support import RestApi
from hag_socket_support import websocket
from hag_state_support import Ha, light_off, light_on
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute


def logger_state() -> list[tuple[str, int, bool, int]]:
    """Each uvicorn logger's level, propagation and handler count, which starting a server must leave as it found them."""
    return [(n, logging.getLogger(n).level, logging.getLogger(n).propagate, len(logging.getLogger(n).handlers))
            for n in ("uvicorn", "uvicorn.error", "uvicorn.access")]


LOGGERS_AT_IMPORT = logger_state()


def _app(ha: Ha) -> Starlette:
    routes = [*RestApi(ha).routes(), WebSocketRoute("/api/websocket", partial(websocket, ha))]
    return Starlette(routes=routes)


class Server:
    def __init__(self, ha: Ha) -> None:
        self.ha = ha
        config = uvicorn.Config(_app(ha), host="127.0.0.1", port=0, ws="wsproto", lifespan="off",
                                log_config=None)
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
    """The stand-in, empty, with its address; reset after the test."""
    stand_in.reset()
    stand_in.service("light", "turn_on", "Turn on a light", {"brightness_pct": "How bright"}, then=light_on)
    stand_in.service("light", "turn_off", "Turn off a light", then=light_off)
    yield stand_in
    stand_in.reset()
