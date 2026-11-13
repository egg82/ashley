"""The etcd calls the referee needs, over etcd's JSON gateway (`/v3/...` on the client port). Not the gRPC API: the
Python gRPC clients either lack TLS (`aetcd`) or are untyped, and the gateway is the same server-side code. int64
fields travel as strings and zero values are left out, so an absent `TTL` or `succeeded` means zero or false."""

import base64
import ssl
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

import httpx2


class EtcdUnavailable(Exception):
    """A call did not get an answer from etcd: no connection, a timeout, or an error status (`status`)."""

    def __init__(self, kind: str, status: int | None = None) -> None:
        super().__init__(kind)
        self.status = status


@dataclass(frozen=True)
class EtcdTls:
    """Paths to the private CA and this client's certificate and key; etcd requires client certificates."""

    ca_file: str
    cert_file: str
    key_file: str

    @classmethod
    def for_url(cls, url: str, ca_file: str, cert_file: str, key_file: str) -> "EtcdTls | None":
        """These paths for an `https` url; None for plain http, which needs none."""
        return cls(ca_file, cert_file, key_file) if url.startswith("https:") else None

    def context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(cafile=self.ca_file)
        # The referee's CA has no keyUsage extension, which Python 3.13's strict mode rejects and OpenSSL's default
        # allows. Chain and hostname are still verified; reissuing the CA means rotating it on every member.
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        ctx.load_cert_chain(self.cert_file, self.key_file)
        return ctx


@dataclass(frozen=True)
class Grant:
    lease_id: int
    ttl: int


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


class EtcdClient(ABC):
    """The etcd calls the lease and the hold make, as etcd answers them; used as an async context, closed on exit.
    Every call raises `EtcdUnavailable` on failure and nothing else."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @abstractmethod
    async def grant(self, ttl: int) -> Grant:
        """A new lease of at least `ttl` seconds (etcd raises a shorter one to its minimum), and the TTL it got."""

    @abstractmethod
    async def keepalive(self, lease_id: int) -> int:
        """The lease's TTL after refreshing it; 0 when it has expired or was revoked."""

    @abstractmethod
    async def claim(self, key: str, value: str, lease_id: int, guard: tuple[str, str] | None) -> bool:
        """Put `key` under the lease if no key of that name exists and, when there is a `guard`, key `guard[0]` holds
        exactly `guard[1]`; whether it did. A put under a lease that is gone raises (status 404)."""

    @abstractmethod
    async def put(self, key: str, value: str, lease_id: int) -> None:
        """Set `key` to `value` under the lease, replacing whatever was there."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete `key`; whether it existed."""

    async def get(self, key: str) -> str | None:
        """The value of `key`, None when it does not exist."""
        return (await self.prefix(key, exact=True)).get(key)

    @abstractmethod
    async def prefix(self, prefix: str, exact: bool = False) -> dict[str, str]:
        """Every key starting with `prefix` and its value, read in one revision; only `prefix` itself when `exact`."""

    @abstractmethod
    async def revoke(self, lease_id: int) -> None:
        """Revoke the lease, deleting the keys under it. A lease already gone counts as revoked."""


Connect = Callable[[float], EtcdClient]
"""A new client whose calls each give up after the given seconds."""


class EtcdGateway(EtcdClient):
    """One HTTP client to one etcd endpoint over the JSON gateway."""

    def __init__(self, url: str, timeout: float, tls: EtcdTls | None = None,
                 transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._client = httpx2.AsyncClient(base_url=url, timeout=timeout, transport=transport,
                                          verify=tls.context() if tls else True)

    @classmethod
    def connect(cls, url: str, tls: EtcdTls | None = None,
                transport: httpx2.AsyncBaseTransport | None = None) -> Connect:
        return lambda timeout: cls(url, timeout, tls, transport)

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post(path, json=body)
        except httpx2.HTTPError as e:
            raise EtcdUnavailable(type(e).__name__) from e
        if resp.status_code != 200:
            raise EtcdUnavailable("status", resp.status_code)
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as e:
            raise EtcdUnavailable(type(e).__name__) from e
        return data

    async def grant(self, ttl: int) -> Grant:
        data = await self._post("/v3/lease/grant", {"TTL": ttl})
        return Grant(lease_id=int(data["ID"]), ttl=int(data["TTL"]))

    async def keepalive(self, lease_id: int) -> int:
        data = await self._post("/v3/lease/keepalive", {"ID": str(lease_id)})
        return int(data.get("result", {}).get("TTL", 0))

    async def claim(self, key: str, value: str, lease_id: int, guard: tuple[str, str] | None) -> bool:
        k = _b64(key)
        compare = [{"key": k, "result": "EQUAL", "target": "CREATE", "create_revision": "0"}]
        if guard is not None:
            compare.append({"key": _b64(guard[0]), "result": "EQUAL", "target": "VALUE", "value": _b64(guard[1])})
        data = await self._post("/v3/kv/txn", {
            "compare": compare,
            "success": [{"request_put": {"key": k, "value": _b64(value), "lease": str(lease_id)}}],
        })
        return bool(data.get("succeeded", False))

    async def put(self, key: str, value: str, lease_id: int) -> None:
        await self._post("/v3/kv/put", {"key": _b64(key), "value": _b64(value), "lease": str(lease_id)})

    async def delete(self, key: str) -> bool:
        data = await self._post("/v3/kv/deleterange", {"key": _b64(key)})
        return int(data.get("deleted", 0)) > 0

    async def prefix(self, prefix: str, exact: bool = False) -> dict[str, str]:
        body = {"key": _b64(prefix)}
        if not exact:
            end = prefix.encode()[:-1] + bytes([prefix.encode()[-1] + 1])
            body["range_end"] = base64.b64encode(end).decode()
        data = await self._post("/v3/kv/range", body)
        try:
            return {base64.b64decode(kv["key"]).decode(): base64.b64decode(kv.get("value", "")).decode()
                    for kv in data.get("kvs", [])}
        except (KeyError, ValueError) as e:
            raise EtcdUnavailable(type(e).__name__) from e

    async def revoke(self, lease_id: int) -> None:
        try:
            await self._post("/v3/lease/revoke", {"ID": str(lease_id)})
        except EtcdUnavailable as e:
            if e.status != 404:
                raise
