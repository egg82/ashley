"""The Bridge over HTTPS with mutual TLS: this app's client certificate (issued by the `ashley-bridges` CA), the bridge's
certificate pinned by fingerprint (`transport`). Each call is one connection in a worker thread. A call logs
`herdr.call` with the call's name, outcome and duration_ms; never an address, a token, a session or text."""

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar, get_args

from .. import logs
from .bridge import Bridge
from .config import HerdrConfig
from .model import Access, BridgeFailed, OutFile, Reason, Screen, Session, SessionList, Whoami
from .transport import ClientCertificate, Request, exchange
from .wire import ClosedBody, SessionBody, SubmittedBody, UploadedBody, body_as, outputs, screen, session, sessions, whoami

log = logging.getLogger("ashley.herdr")
SESSION_ID = re.compile(r"[0-9a-fA-F-]{36}")
ERROR_ROOM = 4096  # a refusal's JSON is read in full even when the file limit asked for is smaller
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
T = TypeVar("T")


def _session_path(session_id: str, tail: str) -> str:
    if SESSION_ID.fullmatch(session_id) is None:
        raise BridgeFailed("not_found")
    return f"/v1/sessions/{session_id.lower()}{tail}"


def _file_path(session_id: str, folder: str, name: str) -> str:
    """The path of one file in a session's `in/` or `out/`; a name the bridge would refuse never leaves this side."""
    if FILE_NAME.fullmatch(name) is None:
        raise BridgeFailed("bad_request")
    return _session_path(session_id, f"/{folder}/{name}")


def _refusal(raw: bytes) -> BridgeFailed:
    """The failure for a non-200 answer: the bridge's own `{"error": code}`, else `unexpected`."""
    try:
        code = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        return BridgeFailed("unexpected")
    return BridgeFailed(code) if code in get_args(Reason) else BridgeFailed("unexpected")


class HttpBridge(Bridge):
    def __init__(self, certificate: ClientCertificate, config: HerdrConfig) -> None:
        self._certificate = certificate
        self._config = config

    async def _call(self, name: str, access: Access, request: Request, parse: Callable[[bytes], T],
                    timeout_s: float | None = None, max_bytes: int | None = None) -> T:
        started = time.monotonic()
        outcome = "ok"
        try:
            status, body = await asyncio.to_thread(exchange, access, self._certificate, request,
                                                   timeout_s or self._config.timeout_s,
                                                   self._config.response_max_bytes if max_bytes is None else max_bytes)
            if status != 200:
                raise _refusal(body)
            return parse(body)
        except BridgeFailed as e:
            outcome = e.reason
            raise
        finally:
            logs.info(log, "herdr.call", call=name, outcome=outcome, duration_ms=int((time.monotonic() - started) * 1000))

    async def whoami(self, access: Access) -> Whoami:
        return await self._call("whoami", access, Request("GET", "/v1/whoami"), whoami)

    async def sessions(self, access: Access) -> SessionList:
        return await self._call("sessions", access, Request("GET", "/v1/sessions"), sessions)

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        path = _session_path(session_id, f"/read?lines={int(lines)}")
        return await self._call("read", access, Request("GET", path), screen)

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        request = Request("POST", _session_path(session_id, "/prompt"), json.dumps({"text": text}).encode(), changes=True)
        await self._call("prompt", access, request, lambda raw: _confirmed(body_as(SubmittedBody, raw).submitted))

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        wanted = {"dir": directory, "label": label, **({"model": model} if model else {})}
        request = Request("POST", "/v1/sessions", json.dumps(wanted).encode(), changes=True)
        return await self._call("start", access, request, lambda raw: session(body_as(SessionBody, raw)),
                                self._config.start_timeout_s)

    async def close(self, access: Access, session_id: str) -> None:
        request = Request("POST", _session_path(session_id, "/close"), b"{}", changes=True)
        await self._call("close", access, request, lambda raw: _confirmed(body_as(ClosedBody, raw).closed))

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        request = Request("PUT", _file_path(session_id, "in", name), data, changes=True, binary=True)
        await self._call("upload", access, request, lambda raw: body_as(UploadedBody, raw), self._config.start_timeout_s)

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        return await self._call("outputs", access, Request("GET", _session_path(session_id, "/out")), outputs)

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        request = Request("GET", _file_path(session_id, "out", name), binary=True)
        data = await self._call("download", access, request, bytes, self._config.start_timeout_s,
                                max(max_bytes, ERROR_ROOM))
        if len(data) > max_bytes:
            raise BridgeFailed("too_large")
        return data


def _confirmed(done: bool) -> None:
    if not done:
        raise BridgeFailed("unexpected")
