"""`page_fetch.fetch_file`, the request-forgery boundary for a binary file: the same https and public-address checks as
a page, redirects included, plus a host allow-list checked on every hop and a byte limit that refuses the whole body."""

import asyncio

import httpx2
import pytest

from ashley.tools import page_fetch
from ashley.tools.page_fetch import Limits, NoPage, Refused, TooLarge
from page_support import Resolver, redirect, site
from search_support import Fake

HOSTS = frozenset({"files.example"})
URL = "https://files.example/a.stl"
LIMITS = Limits(timeout_s=6, max_redirects=3, max_bytes=100)


def file(fake: Fake, url: str = URL, resolver: Resolver | None = None, limits: Limits = LIMITS) -> bytes:
    return asyncio.run(page_fetch.fetch_file(fake.client(), url, limits, HOSTS, resolver or Resolver()))


def served(body: bytes, kind: str = "application/octet-stream") -> httpx2.Response:
    return httpx2.Response(200, content=body, headers={"content-type": kind})


def test_a_binary_body_of_any_type_comes_back_whole() -> None:
    body = bytes(range(256))[:100]
    assert file(site({URL: served(body)})) == body
    assert file(site({URL: served(body, "text/html")})) == body


def test_a_body_one_byte_over_the_limit_is_refused_whole_by_its_stream_or_its_declared_length() -> None:
    assert file(site({URL: served(b"x" * 100)})) == b"x" * 100
    with pytest.raises(TooLarge):
        file(site({URL: served(b"x" * 101)}))
    declared = httpx2.Response(200, content=b"x" * 10, headers={"content-length": "101"})
    with pytest.raises(TooLarge):
        file(site({URL: declared}))


def test_too_large_is_a_refusal() -> None:
    assert issubclass(TooLarge, Refused)


@pytest.mark.parametrize("url", ["http://files.example/a.stl", "https://other.example/a.stl",
                                 "https://files.example.evil.example/a.stl", "https://evil.example/files.example",
                                 "https://user@other.example/a.stl"])
def test_a_host_off_the_list_or_a_plain_http_address_is_refused_before_any_request(url: str) -> None:
    fake, resolver = site({}), Resolver()
    with pytest.raises(Refused):
        file(fake, url, resolver)
    assert fake.requests == [] and resolver.asked == []


def test_the_host_is_compared_by_its_parsed_name_in_any_case() -> None:
    assert file(site({"https://files.example/a.stl": served(b"ok")}), "https://FILES.example/a.stl") == b"ok"


def test_every_redirect_is_checked_against_the_list_and_the_addresses() -> None:
    fake = site({URL: redirect("https://other.example/a.stl"), "https://other.example/a.stl": served(b"ok")})
    with pytest.raises(Refused):
        file(fake)
    assert [str(r.url) for r in fake.requests] == [URL]
    again = site({URL: redirect("/b.stl"), "https://files.example/b.stl": served(b"ok")})
    assert file(again) == b"ok"
    private = Resolver({"files.example": ["10.1.2.3"]})
    with pytest.raises(Refused):
        file(site({URL: served(b"x")}), resolver=private)
    loop = site({URL: redirect(URL)})
    with pytest.raises(Refused):
        file(loop)
    assert len(loop.requests) == LIMITS.max_redirects + 1


def test_a_failed_status_or_an_unresolvable_host_is_no_page() -> None:
    with pytest.raises(NoPage):
        file(site({}))
    with pytest.raises(NoPage):
        file(site({URL: served(b"x")}), resolver=Resolver({"files.example": None}))
