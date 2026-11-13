"""One S3-compatible endpoint as an object store: a bucket on MinIO or any server that speaks S3's path-style PUT,
GET and ListObjectsV2 with Signature Version 4. Several endpoints are one store through `mirror.MirroredStore`."""

import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx2

from . import sigv4
from .store import CHUNK, ObjectStore, StoreUnavailable

_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def _written(text: str | None, now: datetime) -> datetime:
    try:
        moment = datetime.fromisoformat(text) if text else now
    except ValueError:
        return now
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class S3Store(ObjectStore):
    """`endpoint` is `http(s)://host:port`; `http` is the client to send with, `bucket` an existing bucket. A reply
    other than the expected one, and any failure to reach the server, raise StoreUnavailable."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, http: httpx2.AsyncClient,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._base = endpoint.rstrip("/")
        self._host = urlsplit(self._base).netloc
        self._bucket = bucket
        self._keys = (access_key, secret_key)
        self._http = http
        self._clock = clock

    async def put(self, key: str, data: bytes) -> int:
        reply = await self._send("PUT", self._path(key), {}, data)
        if reply.status_code != 200:
            raise StoreUnavailable(f"put answered {reply.status_code}")
        return 1

    async def get(self, key: str) -> bytes | None:
        reply = await self._send("GET", self._path(key), {}, b"")
        if reply.status_code == 404:
            return None
        if reply.status_code != 200:
            raise StoreUnavailable(f"get answered {reply.status_code}")
        return reply.content

    async def size(self, key: str) -> int | None:
        reply = await self._send("HEAD", self._path(key), {}, b"")
        if reply.status_code == 404:
            return None
        length = reply.headers.get("content-length", "")
        if reply.status_code != 200 or not length.isdigit():
            raise StoreUnavailable(f"head answered {reply.status_code}")
        return int(length)

    async def stream(self, key: str, first: int, last: int) -> AsyncIterator[bytes] | None:
        path = self._path(key)
        headers = {**sigv4.sign("GET", self._host, path, {}, b"", *self._keys, self._clock()),
                   "range": f"bytes={first}-{last}"}
        try:
            reply = await self._http.send(self._http.build_request("GET", self._base + path, headers=headers),
                                          stream=True)
        except httpx2.HTTPError as e:
            raise StoreUnavailable(type(e).__name__) from e
        if reply.status_code != 206 and not (reply.status_code == 200 and first == 0):
            await reply.aclose()
            if reply.status_code == 404:
                return None
            raise StoreUnavailable(f"get answered {reply.status_code}")
        return self._body(reply, last - first + 1)

    @staticmethod
    async def _body(reply: httpx2.Response, wanted: int) -> AsyncIterator[bytes]:
        left = wanted
        try:
            async for chunk in reply.aiter_bytes(CHUNK):
                piece = chunk[:left]
                left -= len(piece)
                yield piece
                if left == 0:
                    return
        except httpx2.HTTPError as e:
            raise StoreUnavailable(type(e).__name__) from e
        finally:
            await reply.aclose()

    async def delete(self, key: str) -> None:
        reply = await self._send("DELETE", self._path(key), {}, b"")
        if reply.status_code not in (200, 204, 404):
            raise StoreUnavailable(f"delete answered {reply.status_code}")

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        """A key whose listing carries no `LastModified` is given now, so it counts as just written."""
        found: dict[str, datetime] = {}
        token = ""
        while True:
            params = {"list-type": "2", "prefix": prefix, **({"continuation-token": token} if token else {})}
            reply = await self._send("GET", f"/{self._bucket}", params, b"")
            if reply.status_code != 200:
                raise StoreUnavailable(f"list answered {reply.status_code}")
            page = ET.fromstring(reply.content)
            for item in page.iter(f"{_NS}Contents"):
                found[item.findtext(f"{_NS}Key") or ""] = _written(item.findtext(f"{_NS}LastModified"), self._clock())
            more = page.findtext(f"{_NS}IsTruncated") == "true"
            token = page.findtext(f"{_NS}NextContinuationToken") or ""
            if not more or not token:
                return found

    async def probe(self) -> int:
        """The status of one signed listing asking for at most one key of the bucket: 200 when the bucket answers to
        these keys, 403 when the keys are refused, 404 when the bucket is not there. Raises StoreUnavailable when the
        server cannot be reached."""
        params = {"list-type": "2", "max-keys": "1"}
        return (await self._send("GET", f"/{self._bucket}", params, b"")).status_code

    def _path(self, key: str) -> str:
        return f"/{self._bucket}/{quote(key, safe='/-_.~')}"

    async def _send(self, method: str, path: str, params: dict[str, str], body: bytes) -> httpx2.Response:
        headers = sigv4.sign(method, self._host, path, params, body, *self._keys, self._clock())
        try:
            return await self._http.request(method, self._base + path, params=params or None, content=body or None,
                                            headers=headers)
        except httpx2.HTTPError as e:
            raise StoreUnavailable(type(e).__name__) from e
