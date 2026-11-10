"""The keeper's calls to the app (`ashley.api.mail_bridge`): fetch the vault, write it back, heartbeat, report an event.
Every call carries the pod's epoch and token. A refusal (the app answered, and said no: 401, 409, 503 or anything else
not 2xx) is `Refused`; an app that could not be reached or answered too slowly is `AppUnreachable`. The keeper treats the
first as the end of Bridge at once, and the second as the end after `fence_s` of none answered; a write-back that cannot
be made is the end either way."""

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

PREFIX = "/api/mail-bridge/keeper"


class Refused(Exception):
    """The app answered with this status and refused."""

    def __init__(self, status: int) -> None:
        super().__init__(f"http {status}")
        self.status = status


class AppUnreachable(Exception):
    """No answer from the app in time."""


Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]
"""(method, url, headers, body, timeout) -> (status, body). Raises OSError when nothing answered."""


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                     timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as got:
            return got.status, got.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise OSError(str(e.reason)) from e


@dataclass(frozen=True)
class Vault:
    generation: int
    vault: bytes | None
    keychain: bytes | None


class AppClient:
    def __init__(self, base_url: str, epoch: int, token: str, timeout_s: float,
                 transport: Transport = urllib_transport) -> None:
        self._base = base_url.rstrip("/")
        self._epoch = epoch
        self._token = token
        self._timeout = timeout_s
        self._transport = transport

    def fetch_vault(self) -> Vault:
        got = self._call("GET", f"/vault?epoch={self._epoch}", None)
        return Vault(int(got["generation"]), _decode(got["vault"]), _decode(got["keychain"]))

    def write_back(self, generation: int, vault: bytes, keychain: bytes) -> int:
        """The generation the app holds now."""
        got = self._call("PUT", "/vault", {"epoch": self._epoch, "generation": generation,
                                           "vault": _encode(vault), "keychain": _encode(keychain)})
        return int(got["generation"])

    def heartbeat(self, certificate_sha256: str | None) -> None:
        self._call("POST", "/heartbeat", {"epoch": self._epoch, "certificate_sha256": certificate_sha256})

    def event(self, user_id: str, state: str | None, sync: str | None, progress: float | None) -> None:
        self._call("POST", "/events", {"epoch": self._epoch, "user_id": user_id, "state": state, "sync": sync,
                                       "progress": progress})

    def _call(self, method: str, path: str, body: Mapping[str, Any] | None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        data = None if body is None else json.dumps(body).encode()
        try:
            status, raw = self._transport(method, self._base + PREFIX + path, headers, data, self._timeout)
        except OSError as e:
            raise AppUnreachable(type(e).__name__) from e
        if not 200 <= status < 300:
            raise Refused(status)
        return {} if not raw else dict(json.loads(raw))


def _encode(blob: bytes) -> str:
    return base64.b64encode(blob).decode()


def _decode(text: str | None) -> bytes | None:
    return None if text is None else base64.b64decode(text)
