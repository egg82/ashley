"""The one place that opens an arbitrary URL: a search result's page, fetched from inside the pod. So it holds the
request-forgery boundary. Only https; the host must resolve to global addresses only, checked before every request,
redirects included; a body of a type that is not text is never read, and one that is is read only up to a limit.
`fetch_file` is the same boundary for a binary file, allowed only from the hosts it is given and refused whole when over
its limit.

A DNS answer that changes between the check and the connect is not covered (`docs/decisions.md`, Search)."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx2

from ..workshop.recipe import Recipe
from . import page_text, recipe_ld

Resolve = Callable[[str], Awaitable[Sequence[str]]]
TYPES = frozenset({"text/html", "text/plain"})
REDIRECTS = frozenset({301, 302, 303, 307, 308})


class Refused(Exception):
    """The page is not one this may read: not https, a host with a non-public address, too many redirects, or a
    content type that is not text."""


class TooLarge(Refused):
    """A file's body is longer than the limit; none of it is kept."""


class NoPage(Exception):
    """The page did not answer: a timeout, a connection error, a name that does not resolve, or a non-2xx status."""


class Status(NoPage):
    """The page answered with a non-2xx `status`."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


@dataclass(frozen=True)
class Limits:
    timeout_s: float
    max_redirects: int
    max_bytes: int


@dataclass(frozen=True)
class Page:
    """The page's readable text, its own `title` (empty for plain text or a page with none), how many bytes of its
    body were read, and the recipe it publishes as schema.org data (`recipe_ld`), None when it publishes none."""

    text: str
    bytes: int
    title: str = ""
    recipe: Recipe | None = None


@dataclass(frozen=True)
class Source:
    """A body as the server sent it: its content `kind` (the type without parameters), decoded `text` and the `bytes`
    read."""

    kind: str
    text: str
    bytes: int


@dataclass(frozen=True)
class Reply:
    """An answer as sent: its `status`, `headers` (names lowercased; a repeated one joined by a comma) and, for a 2xx HTML
    body, the page's `title` (empty otherwise)."""

    status: int
    headers: Mapping[str, str]
    title: str = ""


async def resolve(host: str) -> Sequence[str]:
    """Every address `host` resolves to. Raises OSError when it does not resolve."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def fetch(http: httpx2.AsyncClient, url: str, limits: Limits, resolve: Resolve = resolve) -> Page:
    """The text of the page at `url`, following at most `limits.max_redirects` redirects by hand, each checked as the
    first. Raises Refused or NoPage."""
    return page_of(await fetch_source(http, url, limits, resolve), url)


async def fetch_source(http: httpx2.AsyncClient, url: str, limits: Limits, resolve: Resolve = resolve,
                       headers: Mapping[str, str] | None = None) -> Source:
    """The body at `url` as sent, under the same checks as `fetch` and with `headers` on each request. Raises Refused or
    NoPage."""
    try:
        async with asyncio.timeout(limits.timeout_s):
            return await _follow(http, url, limits, resolve, headers, _read)
    except TimeoutError as e:
        raise NoPage() from e


async def fetch_reply(http: httpx2.AsyncClient, url: str, limits: Limits, resolve: Resolve = resolve) -> Reply:
    """How `url` answers, under the same checks as `fetch` and without raising on a non-2xx status: its final status,
    its headers, and the page's own title when the answer is a successful HTML page. Raises Refused (not https, a
    non-public address, too many redirects) or NoPage (no answer at all)."""
    try:
        async with asyncio.timeout(limits.timeout_s):
            return await _follow(http, url, limits, resolve, None, _read_reply)
    except TimeoutError as e:
        raise NoPage() from e


async def fetch_file(http: httpx2.AsyncClient, url: str, limits: Limits, hosts: Collection[str],
                     resolve: Resolve = resolve) -> bytes:
    """The body at `url` whatever its type, under the same checks as `fetch` and with every request, redirects included,
    to a host whose parsed hostname is one of `hosts`. A body longer than `limits.max_bytes` is refused whole. Raises
    Refused, TooLarge (a Refused) or NoPage."""
    try:
        async with asyncio.timeout(limits.timeout_s):
            return await _follow(http, url, limits, resolve, None, _read_file, frozenset(hosts))
    except TimeoutError as e:
        raise NoPage() from e


def page_of(source: Source, url: str | None) -> Page:
    """The readable text of `source`, read from `url`: an HTML body without its scripts and chrome, with the recipe it
    publishes (not looked for when `url` is None), anything else as it is."""
    if source.kind != "text/html":
        return Page(source.text, source.bytes)
    return Page(page_text.text_of(source.text), source.bytes, page_text.title_of(source.text),
                None if url is None else recipe_ld.recipe_in(source.text, url))


async def _follow[T](http: httpx2.AsyncClient, url: str, limits: Limits, resolve: Resolve,
                     headers: Mapping[str, str] | None, read: Callable[[httpx2.Response, int], Awaitable[T]],
                     hosts: frozenset[str] | None = None) -> T:
    for _ in range(limits.max_redirects + 1):
        await _check(url, resolve, hosts)
        try:
            async with http.stream("GET", url, headers=headers, timeout=limits.timeout_s,
                                   follow_redirects=False) as response:
                location = response.headers.get("location")
                if response.status_code in REDIRECTS and location:
                    url = urljoin(url, location)
                    continue
                return await read(response, limits.max_bytes)
        except httpx2.HTTPError as e:
            raise NoPage() from e
    raise Refused()


async def _check(url: str, resolve: Resolve, hosts: frozenset[str] | None) -> None:
    """Raises Refused unless `url` is https, its host is one of `hosts` when given, and it resolves only to global
    addresses; NoPage when it does not resolve."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or (hosts is not None and parts.hostname.lower() not in hosts):
        raise Refused()
    try:
        addresses = await resolve(parts.hostname)
    except OSError as e:
        raise NoPage() from e
    if not addresses or not all(_public(a) for a in addresses):
        raise Refused()


def _public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


async def _read(response: httpx2.Response, max_bytes: int) -> Source:
    if not response.is_success:
        raise Status(response.status_code)
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind not in TYPES:
        raise Refused()
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk[:max_bytes - len(body)]
        if len(body) >= max_bytes:
            break
    try:
        text = bytes(body).decode(response.charset_encoding or "utf-8", errors="replace")
    except LookupError:
        text = bytes(body).decode("utf-8", errors="replace")
    return Source(kind, text, len(body))


async def _read_reply(response: httpx2.Response, max_bytes: int) -> Reply:
    headers = {name.lower(): response.headers.get(name) or "" for name in response.headers}
    if not response.is_success or headers.get("content-type", "").split(";")[0].strip().lower() != "text/html":
        return Reply(response.status_code, headers)
    source = await _read(response, max_bytes)
    return Reply(response.status_code, headers, page_text.title_of(source.text))


async def _read_file(response: httpx2.Response, max_bytes: int) -> bytes:
    if not response.is_success:
        raise NoPage()
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise TooLarge()
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise TooLarge()
    return bytes(body)
