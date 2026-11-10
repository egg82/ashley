"""Helpers for the blind `read_page` tests. The whole `LookUpTools.call` runs with a scripted `Inference` (`Reader`: each
step is a function of the tool results so far, so a plan can say "read the second result of the first search" without
knowing its number), one `httpx2.MockTransport` that serves both SearXNG (the captured body with its URLs replaced) and
the page hosts, and a fake `loop.getaddrinfo`, which is where the contract says the fetch resolves a host. The one
assumption about construction is `look_up_tools` below; everything else goes through public tool calls."""

import asyncio
import copy
import ipaddress
import json
import socket
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx2
import pytest
from ashley import services
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.model import Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.tools.composite import CompositeTools
from ashley.tools.look_up import LookedUp, LookUpTools
from ashley.tools.look_up_config import LookUpConfig
from ashley.tools.pages import Pages
from ashley.tools.web_search import WebSearchTools
from pydantic import BaseModel, ValidationError
from search_contract_support import CONFIG as SEARCH, SEARXNG_URL
from search_contract_support import SEARXNG, Stub, run

T = TypeVar("T", bound=BaseModel)
CONFIG = LookUpConfig(max_rounds=3, result_chars=100_000, answer_chars=500, max_sources=3, page_timeout_s=6,
                      max_redirects=3, page_bytes=1_000_000, page_chars=6000)
"""The contract's values, except `result_chars`, raised so the look-up's own cut never hides a page's."""
UA = "ashley-test (household assistant)"
SEARX_HOST = "searx.test"
PUBLIC = "93.184.216.34"
NOW = "Tuesday 2026-10-27 14:00"
RUNAWAY = 20
SITES = [f"https://site{i}.test/page{i}" for i in range(1, 9)]
"""The URLs of the default search's eight results; `site<i>.test` is result number `i` when it is the first search."""
NOT_READABLE = "that page cannot be read"
NO_ANSWER = "the page did not answer"
NEEDS_NUMBER = "read_page needs a result number"
NO_SUCH = "no search result with that number"
TWO_READ = "two pages already read"

Responder = Callable[[httpx2.Request], httpx2.Response]


def cfg(**changes: Any) -> LookUpConfig:
    return replace(CONFIG, **changes)


def host_of(request: httpx2.Request) -> str:
    raw = request.headers.get("host", request.url.host)
    return raw[1:raw.index("]")] if raw.startswith("[") else raw.split(":")[0]


def searx_body(urls: list[str]) -> dict[str, Any]:
    """The captured SearXNG body with one result per URL (the captured results, cycled, each given its URL)."""
    body = copy.deepcopy(SEARXNG)
    body["results"] = [{**copy.deepcopy(SEARXNG["results"][i % len(SEARXNG["results"])]), "url": u}
                       for i, u in enumerate(urls)]
    return body


@dataclass
class Net:
    """The internet: SearXNG answers `urls[query]` (else `fallback`) as results; a page host answers with its
    responder (else 404). Every request to a page host is kept in `hits`, every search query in `queries`."""

    pages: dict[str, Responder] = field(default_factory=dict[str, Responder])
    urls: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    fallback: list[str] = field(default_factory=lambda: list(SITES))
    queries: list[str] = field(default_factory=list[str])
    hits: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        host = host_of(request)
        if host == SEARX_HOST:
            query = request.url.params["q"]
            self.queries.append(query)
            return httpx2.Response(200, json=searx_body(self.urls.get(query, self.fallback)))
        self.hits.append(request)
        make = self.pages.get(host)
        return make(request) if make else httpx2.Response(404, text="not found")

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), headers={"User-Agent": UA})

    @property
    def hosts(self) -> list[str]:
        return [host_of(r) for r in self.hits]


def page(body: str | bytes, status: int = 200, ctype: str | None = "text/html; charset=utf-8",
         **headers: str) -> Responder:
    def make(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=body, headers=({"content-type": ctype} if ctype else {}) | headers)

    return make


def redirect(location: str, status: int = 302) -> Responder:
    return page("", status, None, location=location)


def failing(error: Exception) -> Responder:
    def make(request: httpx2.Request) -> httpx2.Response:
        raise error

    return make


class Chunks(httpx2.AsyncByteStream):
    """A body of `count` chunks that counts how many were pulled, so a read that did not stop shows."""

    def __init__(self, chunk: bytes, count: int) -> None:
        self.chunk, self.count, self.pulled = chunk, count, 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.count):
            self.pulled += 1
            yield self.chunk


def streamed(stream: Chunks, ctype: str = "text/plain") -> Responder:
    def make(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": ctype}, stream=stream)

    return make


AddrInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int] | tuple[str, int, int, int]]


@dataclass
class Dns:
    """What `loop.getaddrinfo` answers: `table[host]` when set, else the address itself for a literal, else a public
    address. Every host asked is kept in `asked`, which is how a test proves the fake was the resolver."""

    table: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    asked: list[str] = field(default_factory=list[str])

    def answer(self, host: str, port: int) -> list[AddrInfo]:
        self.asked.append(host)
        literal = host if _is_ip(host) else None
        found = self.table.get(host, [literal or PUBLIC])
        return [_info(a, port) for a in found]


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _info(address: str, port: int) -> AddrInfo:
    if ipaddress.ip_address(address).version == 6:
        return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0))
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))


def install_dns(monkeypatch: pytest.MonkeyPatch) -> Dns:
    dns = Dns()

    async def getaddrinfo(self: asyncio.BaseEventLoop, host: str | bytes | None, port: str | int | None, *,
                          family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> list[AddrInfo]:
        return dns.answer(host.decode() if isinstance(host, bytes) else str(host), int(port or 443))

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    return dns


Ctx = list[ToolResult]
Move = Callable[[Ctx], LookedUp | ToolCalls]
Maker = Callable[[Ctx], tuple[str, dict[str, object]]]


def calls(*makers: Maker) -> Move:
    """One round asking for every maker's call, in order."""
    def move(ctx: Ctx) -> ToolCalls:
        return ToolCalls(tuple(ToolCall(f"c{len(ctx)}_{k}", *m(ctx)) for k, m in enumerate(makers)))

    return move


def finish(text: str = "Open until nine.") -> Move:
    return lambda ctx: LookedUp(found=True, answer=text, sources=["example.org"], references=[])


def web(query: str = "first") -> Maker:
    return lambda ctx: ("search_web", {"query": query})


class _Numbered(BaseModel):
    results: list[dict[str, Any]]


def numbers(ctx: Ctx) -> list[list[int]]:
    """The result numbers of each search_web result in `ctx`, in order."""
    out: list[list[int]] = []
    for r in ctx:
        try:
            found = _Numbered.model_validate_json(r.content)
        except ValidationError:
            continue
        out.append([item["result"] for item in found.results])
    return out


def read(search: int, index: int) -> Maker:
    """read_page of the `index`th result of the `search`th search, by the number that search printed."""
    return lambda ctx: ("read_page", {"result": numbers(ctx)[search][index]})


def read_number(n: int) -> Maker:
    return lambda ctx: ("read_page", {"result": n})


def read_args(arguments: dict[str, object]) -> Maker:
    return lambda ctx: ("read_page", arguments)


@dataclass
class Seen:
    task: Task
    prompt: Prompt


@dataclass
class Reader(Inference):
    """Answers step `n` with `plan[n](results so far)`; past the plan, a "gave up" answer. Keeps every step, every
    result, and the calls it asked for."""

    plan: list[Move] = field(default_factory=list[Move])
    seen: list[Seen] = field(default_factory=list[Seen])
    results: Ctx = field(default_factory=list[ToolResult])
    asked: list[ToolCall] = field(default_factory=list[ToolCall])

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.seen.append(Seen(task, prompt))
        if len(self.seen) > RUNAWAY:
            raise InferenceUnavailable("the scripted model was asked too often")
        last = prompt.messages[-1]
        if isinstance(last, ToolResults):
            self.results += last.results
        n = len(self.seen) - 1
        got = self.plan[n](self.results) if n < len(self.plan) else LookedUp(found=False, answer="gave up", sources=[], references=[])
        if isinstance(got, ToolCalls):
            self.asked += got.calls
            return got
        return output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("look_up steps; it never calls generate")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")

    def reads(self) -> list[tuple[ToolCall, ToolResult]]:
        """Each read_page call the model made with its result."""
        by_id = {r.call_id: r for r in self.results}
        return [(c, by_id[c.id]) for c in self.asked if c.name == "read_page"]


@dataclass
class Run:
    result: ToolResult
    brain: Reader

    @property
    def pages(self) -> list[ToolResult]:
        return [r for _, r in self.brain.reads()]

    def searches(self) -> list[ToolResult]:
        by_id = {r.call_id: r for r in self.brain.results}
        return [by_id[c.id] for c in self.brain.asked if c.name == "search_web"]


def look_up_tools(net: Net, config: LookUpConfig) -> LookUpTools:
    """As `wiring` builds it: a fresh Composite of the web's pages and places for every look-up. This is the only
    line the tests assume about construction."""
    http = net.client()
    web = WebSearchTools(http, SEARCH, SEARXNG_URL)

    def sources() -> CompositeTools:
        return CompositeTools({"web": Pages(web, http, config), "places": Stub("places", ("find_places",))})

    return LookUpTools(sources, config)


class Rig:
    """One `LookUpTools` (so several look-ups can follow each other) over `net`."""

    def __init__(self, net: Net | None = None, config: LookUpConfig = CONFIG) -> None:
        self.net = Net() if net is None else net
        self.tools = look_up_tools(self.net, config)

    def look_up(self, plan: list[Move], question: str = "when does the clinic close?") -> Run:
        brain = Reader(plan=plan)
        services.register(Inference, brain)
        try:
            result = run(self.tools.call(ToolCall("k1", "look_up", {"question": question, "now": NOW})))
        finally:
            services.unregister(Inference)
        return Run(result, brain)


READ_ONE: list[Move] = [calls(web()), calls(read(0, 0)), finish()]


def fetch(responder: Responder, url: str = SITES[0], config: LookUpConfig = CONFIG,
          more: dict[str, Responder] | None = None) -> tuple[ToolResult, Net]:
    """Search once (its only result is `url`), read it, and return that read's result with the net it went through."""
    net = Net(pages={urlsplit(url).hostname or "": responder} | (more or {}), fallback=[url])
    out = Rig(net, config).look_up(READ_ONE)
    assert out.result.is_error is False, "control: the look-up itself works"
    return out.pages[0], net


def ok_text(result: ToolResult) -> str:
    assert result.is_error is False, result.content
    body: dict[str, Any] = json.loads(result.content)
    assert set(body) == {"result", "text"}
    text: str = body["text"]
    return text
