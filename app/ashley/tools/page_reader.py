"""Reading one address as `read_page` reads it: a YouTube video's page as the video's details, a Printables model's page
through its API, a paste or a file view at its plain-text address, any other page as its text. The request-forgery
boundary is `page_fetch`'s. Reached by `read_page` (`pages.Pages`) and by the bench tools, which read a site or video
piece's page from the address the piece stores.

A page whose site refuses the plain fetch (`REFUSING`) is read in the page browser (`looks.browser.PageBrowser`) when
one is wired, and goes through the same `page_fetch.page_of`, so its text and recipe are read alike. The browser says
what it is; a site that refuses it too stays unread."""

import logging
import time
from abc import abstractmethod

import httpx2

from .. import logs, services
from ..looks.browser import BrowseUnavailable, PageBrowser
from ..printables.printables import Printables, PrintablesFailed, model_id_of
from ..workshop import embed
from . import page_fetch, printables_page, raw_source, youtube
from .look_up_config import LookUpConfig

log = logging.getLogger("ashley.tools")
REFUSING = frozenset({401, 403, 429, 503})
"""Statuses a site answers a client it will not serve with (a bot wall's challenge among them): the plain fetch's
answer that sends a page to the page browser. Any other failure is the page's own."""


class PageReader(services.Service):
    @abstractmethod
    async def read(self, url: str, limits: page_fetch.Limits, link: youtube.Link) -> page_fetch.Page:
        """The page at `url`; `link` numbers the links of a video's description. Raises page_fetch.Refused, NoPage."""

    async def reply(self, url: str, limits: page_fetch.Limits) -> page_fetch.Reply:
        """How the site at `url` answers a request, whatever the status, for what a bench shows of a site piece. Raises
        page_fetch.Refused, NoPage (no answer at all). Not abstract: a reader that cannot ask raises NoPage."""
        raise page_fetch.NoPage()

    @classmethod
    def null(cls) -> "PageReader":
        return NullPageReader()


class NullPageReader(PageReader):
    async def read(self, url: str, limits: page_fetch.Limits, link: youtube.Link) -> page_fetch.Page:
        raise page_fetch.NoPage()


class FetchedPageReader(PageReader):
    def __init__(self, http: httpx2.AsyncClient, resolve: page_fetch.Resolve = page_fetch.resolve) -> None:
        self._http = http
        self._resolve = resolve

    async def read(self, url: str, limits: page_fetch.Limits, link: youtube.Link) -> page_fetch.Page:
        model = model_id_of(url)
        if model is not None:
            return await self._model(model)
        video = embed.youtube_id_of(url)
        if video is None:
            return await self._page(url, limits)
        source = await page_fetch.fetch_source(self._http, youtube.WATCH + video, limits, self._resolve,
                                               headers=youtube.BROWSER)
        return youtube.read_page(source, link)

    async def reply(self, url: str, limits: page_fetch.Limits) -> page_fetch.Reply:
        return await page_fetch.fetch_reply(self._http, url, limits, self._resolve)

    async def _page(self, url: str, limits: page_fetch.Limits) -> page_fetch.Page:
        """The page, fetched; when the site answers with a refusing status (`REFUSING`), read in the page browser
        instead, if one is wired."""
        try:
            return await page_fetch.fetch(self._http, raw_source.raw_url(url) or url, limits, self._resolve)
        except page_fetch.Status as e:
            if e.status not in REFUSING or not services.get(PageBrowser).reads():
                raise
        return await browsed_page(url, limits.max_bytes)

    async def _model(self, model_id: str) -> page_fetch.Page:
        try:
            return printables_page.page_of(await services.get(Printables).detail(model_id))
        except PrintablesFailed as e:
            raise page_fetch.NoPage() from e


async def browsed_page(url: str, max_bytes: int) -> page_fetch.Page:
    """The page at `url` (already checked public by the fetch it follows) as the page browser was given it. Raises
    NoPage when it could not be read or did not answer 2xx (Status), Refused when it is not text. Logs `page.browsed`
    with the outcome, status, bytes and duration, never the address."""
    started = time.monotonic()
    try:
        got = await services.get(PageBrowser).read(url)
    except BrowseUnavailable as e:
        _browsed_log(started, "unavailable", 0, 0, str(e))
        raise page_fetch.NoPage() from e
    if not 200 <= got.status < 300:
        _browsed_log(started, "status", got.status, got.bytes, "")
        raise page_fetch.Status(got.status)
    if got.kind not in page_fetch.TYPES:
        _browsed_log(started, "refused", got.status, got.bytes, "")
        raise page_fetch.Refused()
    _browsed_log(started, "ok", got.status, got.bytes, "")
    text = got.text if got.bytes <= max_bytes else got.text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    return page_fetch.page_of(page_fetch.Source(got.kind, text, max_bytes if got.cut else min(got.bytes, max_bytes)), url)


def _browsed_log(started: float, outcome: str, status: int, size: int, reason: str) -> None:
    logs.info(log, "page.browsed", outcome=outcome, status=status, bytes=size, reason=reason or None,
              duration_ms=int((time.monotonic() - started) * 1000))


def limits_of(config: LookUpConfig) -> page_fetch.Limits:
    return page_fetch.Limits(config.page_timeout_s, config.max_redirects, config.page_bytes)


def register(http: httpx2.AsyncClient) -> None:
    """Make the page reader over `http`, the answer to `services.get(PageReader)`."""
    services.register(PageReader, FetchedPageReader(http))
