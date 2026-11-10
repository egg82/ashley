"""The few Kubernetes API calls a sandbox makes, over HTTP, as the app's ServiceAccount: pods in one namespace, and
their logs, and the Secrets a pod is handed (Proton Bridge's keeper token). The token is read from its file on every call, since the kubelet rotates it in place."""

import base64
import logging
from pathlib import Path
from typing import Any

import httpx2

from .loose import as_list, as_object

log = logging.getLogger("ashley.runs")


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
        try:
            token = self._token_file.read_text().strip()
        except OSError as e:
            raise KubeError(f"token unreadable: {type(e).__name__}") from e
        try:
            got = await self._http.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        except httpx2.HTTPError as e:
            raise KubeError(type(e).__name__) from e
        if got.status_code == 404 and missing_ok:
            return None
        if got.status_code >= 400:
            raise KubeError(f"http {got.status_code}")
        return got


def _decoded(secret: dict[str, Any] | None) -> dict[str, str]:
    """A Secret's `data` (base64 values) as text. Raises KubeError for anything else."""
    data = as_object((secret or {}).get("data"))
    if data is None:
        raise KubeError("secret has no data")
    try:
        return {k: base64.b64decode(v, validate=True).decode() for k, v in data.items() if isinstance(v, str)}
    except (ValueError, UnicodeDecodeError) as e:
        raise KubeError("secret is not base64 text") from e
