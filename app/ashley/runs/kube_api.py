"""The few Kubernetes API calls a sandbox makes, over HTTP, as the app's ServiceAccount: pods in one namespace, and
their logs, and the Secrets a pod is handed (Proton Bridge's keeper token). The token is read from its file on every call, since the kubelet rotates it in place."""

import base64
import logging
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

import anyio
import httpx2
from httpx2.websockets import WebSocketDisconnect, WebSocketNetworkError, WebSocketUpgradeError

from .loose import as_list, as_object

log = logging.getLogger("ashley.runs")
STDIN_CHANNEL, STATUS_CHANNEL, CLOSE_SIGNAL = 0, 3, 255
V5, V4 = "v5.channel.k8s.io", "v4.channel.k8s.io"


class KubeError(Exception):
    """The API could not be reached or refused the call. The message is the status code or the error's type, never
    a response body."""


class KubeApi:
    def __init__(self, http: httpx2.AsyncClient, token_file: str) -> None:
        """`http` has the API server as its base URL and trusts its CA."""
        self._http = http
        self._token_file = Path(token_file)

    async def create_pod(self, namespace: str, manifest: dict[str, Any]) -> None:
        await self._call("POST", f"/api/v1/namespaces/{namespace}/pods", json=manifest)

    async def pod(self, namespace: str, name: str) -> dict[str, Any] | None:
        """The pod, or None when there is none by that name."""
        got = await self._call("GET", f"/api/v1/namespaces/{namespace}/pods/{name}", missing_ok=True)
        if got is None:
            return None
        body = as_object(got.json())
        if body is None:
            raise KubeError("pod is not an object")
        return body

    async def pods(self, namespace: str, selector: str) -> list[dict[str, Any]]:
        got = await self._call("GET", f"/api/v1/namespaces/{namespace}/pods", params={"labelSelector": selector})
        assert got is not None
        items = as_list((as_object(got.json()) or {}).get("items"))
        if items is None:
            raise KubeError("pod list has no items")
        return [pod for pod in map(as_object, items) if pod is not None]

    async def log(self, namespace: str, name: str, limit_bytes: int) -> str:
        got = await self._call("GET", f"/api/v1/namespaces/{namespace}/pods/{name}/log",
                               params={"limitBytes": str(limit_bytes)})
        assert got is not None
        return got.content[:limit_bytes].decode("utf-8", errors="replace")

    async def delete_pod(self, namespace: str, name: str) -> bool:
        """Delete it now (no grace period); False when it was already gone."""
        got = await self._call("DELETE", f"/api/v1/namespaces/{namespace}/pods/{name}",
                               json={"gracePeriodSeconds": 0, "propagationPolicy": "Background"}, missing_ok=True)
        return got is not None

    async def attach_stdin(self, namespace: str, name: str, container: str, chunks: AsyncIterable[bytes],
                           timeout_s: float) -> None:
        """Send `chunks` to the standard input of `container` in the pod (pods/attach over a WebSocket), then close it.
        The container's stdin must be open (`stdin` and `stdinOnce`) and the container running. Raises KubeError when the
        attach is refused or broken, or the container's end reports a failure; what `chunks` raises is raised after the
        stream is closed. Needs a server that closes stdin on request (`v5.channel.k8s.io`); on `v4` the close ends the
        attach, which closes stdin too."""
        source_error: Exception | None = None
        try:
            with anyio.fail_after(timeout_s):
                async with self._http.websocket(
                        self._attach_url(namespace, name), params={"container": container, "stdin": "true",
                                                                   "stdout": "false", "stderr": "false", "tty": "false"},
                        headers={"Authorization": f"Bearer {self._token()}"}, subprotocols=[V5, V4],
                        timeout=timeout_s, keepalive_ping_interval_seconds=None) as ws:
                    try:
                        async for chunk in chunks:
                            await ws.send_bytes(bytes([STDIN_CHANNEL]) + chunk)
                    except Exception as e:
                        source_error = e
                    if source_error is None and ws.subprotocol == V5:
                        await ws.send_bytes(bytes([CLOSE_SIGNAL, STDIN_CHANNEL]))
                        await _until_closed(ws)
        except BaseExceptionGroup as group:
            errors = group.split(Exception)[0]
            first = errors.exceptions[0] if errors else None
            raise (first if isinstance(first, KubeError) else KubeError(type(first).__name__)) from group
        except (WebSocketDisconnect, WebSocketNetworkError, WebSocketUpgradeError, httpx2.HTTPError, TimeoutError) as e:
            raise KubeError(type(e).__name__) from e
        if source_error is not None:
            raise source_error

    def _attach_url(self, namespace: str, name: str) -> str:
        base = str(self._http.base_url).rstrip("/")
        scheme = "wss" if base.startswith("https") else "ws"
        return f"{scheme}://{base.split('://', 1)[1]}/api/v1/namespaces/{namespace}/pods/{name}/attach"

    def _token(self) -> str:
        try:
            return self._token_file.read_text().strip()
        except OSError as e:
            raise KubeError(f"token unreadable: {type(e).__name__}") from e

    async def create_secret(self, namespace: str, name: str, labels: dict[str, str], data: dict[str, str]) -> None:
        """An Opaque Secret with `data` (plain text; the call encodes it). Raises KubeError, `http 409` when one by that
        name exists."""
        manifest = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                    "metadata": {"name": name, "labels": labels}, "stringData": data}
        await self._call("POST", f"/api/v1/namespaces/{namespace}/secrets", json=manifest)

    async def secret(self, namespace: str, name: str) -> dict[str, str] | None:
        """The Secret's entries decoded, or None when there is none by that name."""
        got = await self._call("GET", f"/api/v1/namespaces/{namespace}/secrets/{name}", missing_ok=True)
        return None if got is None else _decoded(as_object(got.json()))

    async def secrets(self, namespace: str, selector: str) -> list[str]:
        """The names of the Secrets matching the label selector."""
        got = await self._call("GET", f"/api/v1/namespaces/{namespace}/secrets", params={"labelSelector": selector})
        assert got is not None
        items = as_list((as_object(got.json()) or {}).get("items"))
        if items is None:
            raise KubeError("secret list has no items")
        metas = (as_object((as_object(i) or {}).get("metadata")) or {} for i in items)
        return [m["name"] for m in metas if isinstance(m.get("name"), str)]

    async def delete_secret(self, namespace: str, name: str) -> bool:
        """False when it was already gone."""
        got = await self._call("DELETE", f"/api/v1/namespaces/{namespace}/secrets/{name}", missing_ok=True)
        return got is not None

    async def _call(self, method: str, path: str, missing_ok: bool = False, **kwargs: Any) -> httpx2.Response | None:
        token = self._token()
        try:
            got = await self._http.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        except httpx2.HTTPError as e:
            raise KubeError(type(e).__name__) from e
        if got.status_code == 404 and missing_ok:
            return None
        if got.status_code >= 400:
            raise KubeError(f"http {got.status_code}")
        return got


async def _until_closed(ws: Any) -> None:
    """Read the attach's frames until the server closes it, raising KubeError for a status on the error channel that is
    not a success. An empty status frame carries no status: the API server sends one before the real status."""
    while True:
        try:
            frame: bytes = await ws.receive_bytes()
        except WebSocketDisconnect:
            return
        if frame[:1] == bytes([STATUS_CHANNEL]) and frame[1:].strip() and b'"Success"' not in frame:
            raise KubeError("attach reported a failure")


def _decoded(secret: dict[str, Any] | None) -> dict[str, str]:
    """A Secret's `data` (base64 values) as text. Raises KubeError for anything else."""
    data = as_object((secret or {}).get("data"))
    if data is None:
        raise KubeError("secret has no data")
    try:
        return {k: base64.b64decode(v, validate=True).decode() for k, v in data.items() if isinstance(v, str)}
    except (ValueError, UnicodeDecodeError) as e:
        raise KubeError("secret is not base64 text") from e
