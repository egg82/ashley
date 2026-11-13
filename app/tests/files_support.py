"""Shared by the object-store suites: sample files whose signatures the config knows, and a fake S3 server for
`httpx2.MockTransport` that checks a request is signed and keeps objects per bucket."""

import asyncio
import functools
import re
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec
from urllib.parse import parse_qs, unquote

import httpx2

P = ParamSpec("P")


def sync(test: Callable[P, Coroutine[Any, Any, None]]) -> Callable[P, None]:
    """An async test run to its end on its own event loop (the suite has no async plugin)."""

    @functools.wraps(test)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(test(*args, **kwargs))

    return run

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
JPEG = bytes.fromhex("ffd8ffe000104a464946") + b"\x00" * 20
GIF = b"GIF89a" + b"\x00" * 20
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n"
ZIP = b"PK\x03\x04" + b"\x00" * 26
CSV = b"a,b\n1,2\n"
HTML = b"<!doctype html><script>alert(1)</script>"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00" + b"\x00" * 20
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00" + b"\x00" * 20
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"\x00" * 20
WEBM = bytes.fromhex("1a45dfa3") + b"\x9fB\x86\x81\x01" + b"\x00" * 20
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 20
OGG = b"OggS\x00\x02" + b"\x00" * 20
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20
AVI = b"RIFF\x24\x00\x00\x00AVI LIST" + b"\x00" * 20
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 16


class FakeS3:
    """Path-style S3 over `bucket`. `fail` is a status every request answers when set; `page` is how many keys a
    listing returns at a time. `signed` counts requests that carried a SigV4 authorization."""

    def __init__(self, bucket: str = "ashley", page: int = 1000) -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.modified: dict[str, str] = {}
        self.fail: int | None = None
        self.page = page
        self.signed = 0
        self.unsigned = 0
        self.sent = 0

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        auth = request.headers.get("authorization", "")
        if auth.startswith("AWS4-HMAC-SHA256 Credential=") and "x-amz-date" in request.headers:
            self.signed += 1
        else:
            self.unsigned += 1
        if self.fail is not None:
            return httpx2.Response(self.fail)
        path = unquote(request.url.path)
        if request.method == "GET" and path == f"/{self.bucket}":
            return self._list(parse_qs(request.url.query.decode()))
        match = re.fullmatch(rf"/{self.bucket}/(.+)", path)
        if match is None:
            return httpx2.Response(404)
        key = match.group(1)
        if request.method == "PUT":
            self.objects[key] = request.content
            return httpx2.Response(200)
        if request.method == "HEAD":
            return httpx2.Response(200, headers={"content-length": str(len(self.objects[key]))}) if key in self.objects else httpx2.Response(404)
        if request.method == "GET" and key in self.objects:
            return self._body(self.objects[key], request.headers.get("range"))
        if request.method == "GET":
            return httpx2.Response(404)
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx2.Response(204)
        return httpx2.Response(405)

    def _body(self, data: bytes, asked: str | None) -> httpx2.Response:
        found = re.fullmatch(r"bytes=(\d+)-(\d+)", asked or "")
        if found is None:
            self.sent += len(data)
            return httpx2.Response(200, content=data)
        first, last = int(found[1]), min(int(found[2]), len(data) - 1)
        self.sent += last - first + 1
        return httpx2.Response(206, content=data[first:last + 1],
                               headers={"content-range": f"bytes {first}-{last}/{len(data)}"})

    def _list(self, query: dict[str, list[str]]) -> httpx2.Response:
        prefix = query.get("prefix", [""])[0]
        after = query.get("continuation-token", [""])[0]
        keys = sorted(k for k in self.objects if k.startswith(prefix) and k > after)
        shown, more = keys[:self.page], len(keys) > self.page
        ns = "http://s3.amazonaws.com/doc/2006-03-01/"
        body = f'<ListBucketResult xmlns="{ns}"><IsTruncated>{"true" if more else "false"}</IsTruncated>'
        if more:
            body += f"<NextContinuationToken>{shown[-1]}</NextContinuationToken>"
        body += "".join(f"<Contents><Key>{k}</Key>{self._stamp(k)}</Contents>" for k in shown) + "</ListBucketResult>"
        return httpx2.Response(200, content=body.encode())

    def _stamp(self, key: str) -> str:
        return f"<LastModified>{self.modified[key]}</LastModified>" if key in self.modified else ""
