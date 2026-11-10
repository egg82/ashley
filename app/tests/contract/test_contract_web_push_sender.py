"""Blind contract tests for `Sender` (`WebPushSender`): one notification to one browser, the payload encrypted to the
browser's keys, a push service answering 404 or 410 reported `gone`, any other failure `failed` with its status, a
redirect never followed, and nothing raised for what a push service or the network does. The push service is a local
server that answers a scripted status; the browser's keys are a real P-256 pair."""

import asyncio
import base64
import os
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from ashley.channels.push import config as push_config
from ashley.channels.push.sender import Notification, Sent, WebPushSender
from ashley.channels.push.subscriptions import Browser
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from web_push_support import MARK, settings

TTL, TIMEOUT = 4321, 0.4
NOTIFICATION = Notification("Ashley", "Here is the link " + MARK, "/")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def real_browser(endpoint: str) -> Browser:
    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return Browser(endpoint, _b64(point), _b64(os.urandom(16)))


@dataclass
class Service:
    """A push service on localhost: answers `status` (with `location` for a redirect, after `delay_s`), records each
    request as (path, headers, body)."""

    port: int = 0
    status: int = 201
    location: str = ""
    delay_s: float = 0.0
    seen: list[tuple[str, dict[str, str], bytes]] = field(default_factory=list[tuple[str, dict[str, str], bytes]])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/push/{MARK}"


def serve() -> Generator[Service]:
    state = Service()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            state.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            if state.delay_s:
                threading.Event().wait(state.delay_s)
            self.send_response(state.status)
            if state.location:
                self.send_header("Location", state.location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            state.seen.append((self.path, {}, b""))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()


@pytest.fixture
def service() -> Generator[Service]:
    yield from serve()


@pytest.fixture
def elsewhere() -> Generator[Service]:
    yield from serve()


def sender() -> WebPushSender:
    identity = push_config.vapid(settings())
    assert identity is not None
    return WebPushSender(identity, TTL, TIMEOUT)


def send(to: Browser) -> Sent:
    return asyncio.run(sender().send(to, NOTIFICATION))


def test_an_accepted_push_is_ok_and_reaches_the_endpoint_once(service: Service) -> None:
    got = send(real_browser(service.url))
    assert got.outcome == "ok"
    ((path, _, _),) = service.seen
    assert path == f"/push/{MARK}"


def test_the_message_is_encrypted_and_carries_the_ttl_and_a_vapid_signature(service: Service) -> None:
    send(real_browser(service.url))
    ((_, headers, body),) = service.seen
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["ttl"] == str(TTL)
    scheme, _, token = headers["authorization"].partition(" ")
    assert scheme.lower() in ("vapid", "webpush") and token.count(".") == 2
    assert body and MARK.encode() not in body and b"Ashley" not in body


@pytest.mark.parametrize("status", [404, 410])
def test_a_push_service_saying_the_subscription_is_gone_is_gone_with_its_status(service: Service, status: int) -> None:
    service.status = status
    assert send(real_browser(service.url)) == Sent("gone", status)


@pytest.mark.parametrize("status", [400, 401, 403, 413, 429, 500, 502, 503])
def test_any_other_refusal_is_failed_with_its_status(service: Service, status: int) -> None:
    service.status = status
    assert send(real_browser(service.url)) == Sent("failed", status)


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_not_followed_and_is_a_failure(service: Service, elsewhere: Service, status: int) -> None:
    service.status, service.location = status, elsewhere.url
    got = send(real_browser(service.url))
    assert got.outcome == "failed"
    assert elsewhere.seen == []


def test_an_endpoint_that_cannot_be_reached_is_failed_not_raised(service: Service) -> None:
    dead = real_browser(service.url.replace(str(service.port), "1"))
    assert send(dead) == Sent("failed", None)


def test_a_push_service_slower_than_the_timeout_is_failed_not_raised(service: Service) -> None:
    service.delay_s = TIMEOUT * 4
    got = send(real_browser(service.url))
    assert got.outcome == "failed"


def test_keys_that_are_not_keys_are_failed_not_raised(service: Service) -> None:
    assert send(Browser(service.url, "AAAA", "BBBB")).outcome == "failed"
