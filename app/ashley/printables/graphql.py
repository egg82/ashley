"""Printables through its public GraphQL API, as a visitor who is not logged in. Every value a caller supplied goes in
as a GraphQL variable, never into the query text."""

import logging
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, ValidationError

from .. import logs
from .config import PrintablesConfig
from .model import Detail, Model, ModelFile, Reason
from .printables import Printables, PrintablesFailed

log = logging.getLogger("ashley.printables")

_FIELDS = ("id name slug summary likesCount downloadCount makesCount ratingAvg user{publicUsername} "
           "stls{id name fileSize}")
SEARCH = "query($q:String!,$n:Int){searchPrints2(query:$q,limit:$n){items{" + _FIELDS + "}}}"
DETAIL = ("query($id:ID!){print(id:$id){" + _FIELDS + " description datePublished license{name} category{name}}}")
LINK = ("mutation($file:ID!,$model:ID!){getDownloadLink(id:$file,printId:$model,fileType:stl,source:model_detail)"
        "{ok output{link}}}")


class _User(BaseModel):
    publicUsername: str | None = None


class _File(BaseModel):
    id: str
    name: str
    fileSize: int | None = None


class _Print(BaseModel):
    id: str
    name: str
    slug: str = ""
    summary: str | None = None
    likesCount: int = 0
    downloadCount: int = 0
    makesCount: int = 0
    ratingAvg: str | None = None
    user: _User | None = None
    stls: list[_File] = []


class _Named(BaseModel):
    name: str | None = None


class _Full(_Print):
    description: str | None = None
    datePublished: str | None = None
    license: _Named | None = None
    category: _Named | None = None


class _Search(BaseModel):
    items: list[_Print]


class _Output(BaseModel):
    link: str | None = None


class _Link(BaseModel):
    ok: bool
    output: _Output | None = None


class _Data(BaseModel):
    searchPrints2: _Search | None = None
    print: _Full | None = None
    getDownloadLink: _Link | None = None


class _Body(BaseModel):
    data: _Data | None = None


Fetch = Callable[[str, int], Awaitable[bytes]]
"""Opens an address and returns its body, at most the given bytes; raises PrintablesFailed. Supplied by the composition
root, since opening an address is the request-forgery boundary (`ashley.tools.page_fetch`) and this package imports
neither it nor its limits."""


class GraphqlPrintables(Printables):
    def __init__(self, http: httpx2.AsyncClient, config: PrintablesConfig, fetch: Fetch) -> None:
        self._http = http
        self._config = config
        self._fetch = fetch

    async def search(self, query: str) -> list[Model]:
        started = time.monotonic()
        data = await self._ask("search", started, SEARCH, {"q": query, "n": self._config.results})
        found = data.searchPrints2
        if found is None:
            raise self._failed("search", started, "unexpected")
        logs.info(log, "printables.call", call="search", outcome="ok", count=len(found.items), duration_ms=_ms(started))
        return [self._model(p) for p in found.items[:self._config.results]]

    async def detail(self, model_id: str) -> Detail:
        started = time.monotonic()
        data = await self._ask("detail", started, DETAIL, {"id": _digits(model_id)})
        full = data.print
        if full is None:
            raise self._failed("detail", started, "not_found")
        logs.info(log, "printables.call", call="detail", outcome="ok", count=len(full.stls), duration_ms=_ms(started))
        return Detail(self._model(full), full.description or "", _name(full.license), _name(full.category),
                      (full.datePublished or "")[:10])

    async def download(self, model_id: str, file_id: str, max_bytes: int) -> bytes:
        started = time.monotonic()
        link = await self._link(model_id, file_id, started)
        try:
            data = await self._fetch(link, max_bytes)
        except PrintablesFailed as e:
            raise self._failed("download", started, e.reason) from e
        logs.info(log, "printables.call", call="download", outcome="ok", count=len(data), duration_ms=_ms(started))
        return data

    async def _link(self, model_id: str, file_id: str, started: float) -> str:
        data = await self._ask("link", started, LINK, {"model": _digits(model_id), "file": _digits(file_id)})
        link = data.getDownloadLink
        if link is None:
            raise self._failed("link", started, "unexpected")
        if not link.ok or link.output is None or not link.output.link:
            raise self._failed("link", started, "needs_login")
        parts = urlsplit(link.output.link)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in self._config.file_hosts:
            raise self._failed("link", started, "unexpected")
        return link.output.link

    async def _ask(self, call: str, started: float, query: str, variables: dict[str, object]) -> _Data:
        try:
            response = await self._http.post(self._config.api_url, json={"query": query, "variables": variables},
                                             timeout=self._config.timeout_s)
        except httpx2.HTTPError as e:
            raise self._failed(call, started, "unreachable") from e
        if not response.is_success:
            raise self._failed(call, started, "unreachable")
        try:
            body = _Body.model_validate_json(response.content)
        except ValidationError as e:
            raise self._failed(call, started, "unexpected") from e
        if body.data is None:
            raise self._failed(call, started, "unexpected")
        return body.data

    def _failed(self, call: str, started: float, reason: Reason) -> PrintablesFailed:
        logs.info(log, "printables.call", call=call, outcome=reason, count=0, duration_ms=_ms(started))
        return PrintablesFailed(reason)

    def _model(self, p: _Print) -> Model:
        slug = f"-{p.slug}" if p.slug else ""
        return Model(p.id, p.name, f"{self._config.site_url}/model/{p.id}{slug}", (p.user.publicUsername or "") if p.user else "",
                     (p.summary or "").strip(), p.likesCount, p.downloadCount, p.makesCount, _rating(p.ratingAvg),
                     tuple(ModelFile(f.id, f.name, f.fileSize or 0) for f in p.stls))


def _digits(value: str) -> str:
    if not value.isascii() or not value.isdigit():
        raise PrintablesFailed("not_found")
    return value


def _rating(value: str | None) -> float | None:
    try:
        return None if value is None else round(float(value), 1)
    except ValueError:
        return None


def _name(named: _Named | None) -> str:
    return (named.name or "") if named else ""


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
