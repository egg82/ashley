"""A site piece's frameability through the real app over a real database: unknown until measured, measured once from the
site's headers in the background and recorded on the bench, and unknown (never refused) when the site cannot be asked."""

import asyncio
import threading
import time
from collections.abc import Generator

import psycopg
import pytest
from ashley import services
from ashley.api.workshop_models import BenchPiece
from ashley.tools import page_fetch, page_text
from ashley.tools import site_probe
from ashley.tools.page_reader import NullPageReader, PageReader
from ashley.workshop.frame_probe import FrameProbe
from fastapi.testclient import TestClient
from respond_support import ALANA
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import wired as wired
from test_bench_files_routes import Box, box as box, detail
from test_workshop_routes import command, opened

URL = "https://makerworld.example/en/models/587563"


class Answering(NullPageReader):
    """Answers every address once `release` is set, with `answer` or by raising `failure`; counts the questions."""

    def __init__(self, answer: page_fetch.Reply | Exception) -> None:
        self.answer, self.asked, self.release = answer, 0, threading.Event()

    async def reply(self, url: str, limits: page_fetch.Limits) -> page_fetch.Reply:
        self.asked += 1
        while not self.release.is_set():
            await asyncio.sleep(0.005)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture(autouse=True)
def reader() -> Generator[None]:
    site_probe.register()
    yield
    services.unregister(PageReader)
    services.unregister(FrameProbe)


def added(client: TestClient, bench: int, kind: str, body: str) -> int:
    status, got = command(client, bench, {"type": "add", "kind": kind, "title": "t", "body": body, "size": "medium"})
    assert status == 200
    return int(got["piece_id"] or 0)


def piece(client: TestClient, bench: int, piece_id: int) -> BenchPiece:
    return next(p for p in detail(client, bench).pieces if p.id == piece_id)


def recorded(db_url: str) -> list[tuple[bool | None, str]]:
    with psycopg.connect(db_url) as conn:
        return [(r[0], r[1]) for r in conn.execute("SELECT frameable, title FROM bench_site_frames ORDER BY url").fetchall()]


def wait_for_a_record(db_url: str) -> list[tuple[bool | None, str]]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if found := recorded(db_url):
            return found
        time.sleep(0.01)
    return []


def frameable_of(found: BenchPiece) -> object:
    assert found.site is not None
    return found.site.frameable


@pytest.mark.parametrize("answer,expected,title", [
    (page_fetch.Reply(403, {"x-frame-options": "SAMEORIGIN", "cf-mitigated": "challenge"}), False, ""),
    (page_fetch.Reply(200, {"x-frame-options": "DENY"}, "Cable holder"), False, "Cable holder"),
    (page_fetch.Reply(200, {"content-security-policy": "frame-ancestors https://ashley.test"}, "Docs"), True, "Docs"),
    (page_fetch.Reply(200, {}, "Docs"), True, "Docs"),
], ids=["challenge", "deny", "csp-allows-us", "no-headers"])
def test_a_site_is_unknown_until_asked_then_what_its_headers_say(box: Box, db_url: str, answer: page_fetch.Reply,
                                                                expected: bool, title: str) -> None:
    asking = Answering(answer)
    services.register(PageReader, asking)
    client = box(ALANA)
    bench = opened(client).id
    made = added(client, bench, "site", URL)
    assert frameable_of(piece(client, bench, made)) is None
    asking.release.set()
    assert wait_for_a_record(db_url) == [(expected, title)]
    after = piece(client, bench, made)
    assert frameable_of(after) is expected and after.site is not None and after.site.title == title
    piece(client, bench, made)
    assert asking.asked == 1


@pytest.mark.xfail(strict=True, reason="a NUL in a page's title is refused by the frames insert, which is lost")
def test_a_page_title_with_a_nul_is_recorded_with_the_nul_removed(box: Box, db_url: str) -> None:
    title = page_text.title_of("<html><head><title>Cable\x00 holder</title></head></html>")
    asking = Answering(page_fetch.Reply(200, {}, title))
    asking.release.set()
    services.register(PageReader, asking)
    client = box(ALANA)
    bench = opened(client).id
    piece(client, bench, added(client, bench, "site", URL))
    assert wait_for_a_record(db_url) == [(True, "Cable holder")]


@pytest.mark.parametrize("failure", [page_fetch.NoPage(), page_fetch.Refused()], ids=["no-answer", "refused"])
def test_a_site_that_cannot_be_asked_stays_unknown_and_is_not_asked_again(box: Box, db_url: str,
                                                                          failure: Exception) -> None:
    asking = Answering(failure)
    asking.release.set()
    services.register(PageReader, asking)
    client = box(ALANA)
    bench = opened(client).id
    made = added(client, bench, "site", URL)
    piece(client, bench, made)
    assert wait_for_a_record(db_url) == [(None, "")]
    assert frameable_of(piece(client, bench, made)) is None
    piece(client, bench, made)
    assert asking.asked == 1


def test_only_a_site_piece_with_an_address_has_a_site(box: Box) -> None:
    asking = Answering(page_fetch.Reply(200, {}))
    asking.release.set()
    services.register(PageReader, asking)
    client = box(ALANA)
    bench = opened(client).id
    note, empty = added(client, bench, "note", URL), added(client, bench, "site", "")
    assert piece(client, bench, note).site is None and piece(client, bench, empty).site is None
    assert asking.asked == 0


def test_an_address_taken_off_the_bench_loses_its_measure_when_the_next_is_recorded(box: Box, db_url: str) -> None:
    asking = Answering(page_fetch.Reply(200, {"x-frame-options": "DENY"}))
    asking.release.set()
    services.register(PageReader, asking)
    client = box(ALANA)
    bench = opened(client).id
    old = added(client, bench, "site", URL)
    piece(client, bench, old)
    assert len(wait_for_a_record(db_url)) == 1
    status, _ = command(client, bench, {"type": "edit", "piece_id": old, "base_version": 1, "title": "t",
                                         "body": "https://other.example/x"})
    assert status == 200
    piece(client, bench, old)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and asking.asked < 2:
        time.sleep(0.01)
    time.sleep(0.2)
    assert [t for _, t in recorded(db_url)] == [""] and asking.asked == 2
    with psycopg.connect(db_url) as conn:
        assert [r[0] for r in conn.execute("SELECT url FROM bench_site_frames").fetchall()] == ["https://other.example/x"]
