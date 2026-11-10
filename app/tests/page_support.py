"""Helpers for reading pages without the network: a resolver that answers from a table and records each host asked,
web pages served by URL from an in-process transport, and the captured page (`search_captures/clinic-page.html`,
an invented urgent-care listing in the shape of a directory page)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import httpx2

from search_support import CAPTURES, Fake

PAGE_HTML = (CAPTURES / "clinic-page.html").read_text(encoding="utf-8")
PUBLIC = "93.184.215.14"


@dataclass
class Resolver:
    """Each host's addresses from `table`, any other host `PUBLIC`; a host mapped to None does not resolve."""

    table: Mapping[str, Sequence[str] | None] = field(default_factory=dict[str, Sequence[str] | None])
    asked: list[str] = field(default_factory=list[str])

    async def __call__(self, host: str) -> Sequence[str]:
        self.asked.append(host)
        addresses = self.table.get(host, [PUBLIC])
        if addresses is None:
            raise OSError("no such host")
        return addresses


def html(body: str | bytes, status: int = 200, kind: str = "text/html; charset=utf-8") -> httpx2.Response:
    return httpx2.Response(status, content=body.encode() if isinstance(body, str) else body,
                           headers={"content-type": kind})


def redirect(location: str, status: int = 302) -> httpx2.Response:
    return httpx2.Response(status, headers={"location": location})


def site(pages: Mapping[str, httpx2.Response]) -> Fake:
    """Serves each URL its response; any other URL is a 404."""
    return Fake(lambda request: pages.get(str(request.url), httpx2.Response(404)))
