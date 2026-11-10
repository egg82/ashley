"""`page_fetch.fetch`, the request-forgery boundary: https only, public addresses only (checked again after every
redirect), redirects capped, only text read and only up to the byte cap. No test resolves a real name or opens a
socket: the resolver is a table and the pages come from an in-process transport."""

import asyncio
from collections.abc import AsyncIterator

import httpx2
import pytest

from ashley.tools import page_fetch
from ashley.tools.page_fetch import Limits, NoPage, Page, Refused
from page_support import PAGE_HTML, PUBLIC, Resolver, html, redirect, site
from search_support import Fake, raising

LIMITS = Limits(timeout_s=6, max_redirects=3, max_bytes=1_000_000)
URL = "https://clinic.example/hours"


def fetch(fake: Fake, url: str = URL, resolver: Resolver | None = None, limits: Limits = LIMITS) -> Page:
    return asyncio.run(page_fetch.fetch(fake.client(), url, limits, resolver or Resolver()))


def test_a_page_comes_back_as_its_text_with_the_bytes_read() -> None:
    fake = site({URL: html(PAGE_HTML)})
    page = fetch(fake)
    assert "Sun8:00am - 5:00pm" in page.text and "<" not in page.text
    assert page.bytes == len(PAGE_HTML.encode())
    (request,) = fake.requests
    assert request.method == "GET" and str(request.url) == URL
    assert request.extensions["timeout"]["read"] == LIMITS.timeout_s


def test_plain_text_is_kept_as_it_is_and_the_charset_is_honoured() -> None:
    page = fetch(site({URL: html("caf\xe9 <b>open</b>".encode("latin-1"), kind="text/plain; charset=iso-8859-1")}))
    assert page.text == "café <b>open</b>"


def test_the_clients_user_agent_goes_with_the_request() -> None:
    fake = site({URL: html("<p>x</p>")})
    asyncio.run(page_fetch.fetch(fake.client({"User-Agent": "ashley-test"}), URL, LIMITS, Resolver()))
    assert fake.requests[0].headers["user-agent"] == "ashley-test"


@pytest.mark.parametrize("url", ["http://clinic.example/hours", "ftp://clinic.example/", "file:///etc/passwd",
                                 "https:///no-host", "clinic.example/hours"])
def test_anything_but_https_is_refused_before_any_request(url: str) -> None:
    fake, resolver = site({}), Resolver()
    with pytest.raises(Refused):
        fetch(fake, url, resolver)
    assert fake.requests == [] and resolver.asked == []


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "192.168.1.20", "169.254.169.254", "::1", "fd00::1",
                                     "100.64.0.1", "172.16.5.4", "0.0.0.0", "::ffff:127.0.0.1", "fe80::1", "not-an-ip"])
def test_a_host_with_a_non_public_address_is_refused_before_any_request(address: str) -> None:
    fake, resolver = site({URL: html("<p>x</p>")}), Resolver({"clinic.example": [address]})
    with pytest.raises(Refused):
        fetch(fake, resolver=resolver)
    assert resolver.asked == ["clinic.example"] and fake.requests == []


def test_a_public_ipv6_address_is_read() -> None:
    assert fetch(site({URL: html("<p>x</p>")}), resolver=Resolver({"clinic.example": ["2606:4700::1111"]})).text == "x"


def test_one_private_address_among_public_ones_is_refused() -> None:
    fake = site({URL: html("<p>x</p>")})
    with pytest.raises(Refused):
        fetch(fake, resolver=Resolver({"clinic.example": [PUBLIC, "192.168.1.20"]}))
    assert fake.requests == []


def test_an_address_literal_as_the_host_is_checked_too() -> None:
    fake = site({})
    with pytest.raises(Refused):
        fetch(fake, "https://10.0.0.8/admin", Resolver({"10.0.0.8": ["10.0.0.8"]}))
    assert fake.requests == []


def test_no_addresses_is_refused_and_no_such_host_did_not_answer() -> None:
    with pytest.raises(Refused):
        fetch(site({}), resolver=Resolver({"clinic.example": []}))
    with pytest.raises(NoPage):
        fetch(site({}), resolver=Resolver({"clinic.example": None}))


def test_a_redirect_is_followed_by_hand_and_a_relative_one_resolved() -> None:
    fake = site({URL: redirect("/moved"), "https://clinic.example/moved": redirect("https://www.clinic.example/a", 301),
                 "https://www.clinic.example/a": html("<p>here</p>")})
    resolver = Resolver()
    assert fetch(fake, resolver=resolver).text == "here"
    assert [str(r.url) for r in fake.requests] == [
        URL, "https://clinic.example/moved", "https://www.clinic.example/a"]
    assert resolver.asked == ["clinic.example", "clinic.example", "www.clinic.example"]


def test_a_redirect_to_a_private_host_is_refused_before_it_is_requested() -> None:
    fake = site({URL: redirect("https://router.lan/admin"), "https://router.lan/admin": html("<p>secret</p>")})
    resolver = Resolver({"router.lan": ["192.168.1.1"]})
    with pytest.raises(Refused):
        fetch(fake, resolver=resolver)
    assert [str(r.url) for r in fake.requests] == [URL]
    assert resolver.asked == ["clinic.example", "router.lan"]


def test_a_redirect_to_http_is_refused_before_it_is_requested() -> None:
    fake = site({URL: redirect("http://clinic.example/hours"), "http://clinic.example/hours": html("<p>x</p>")})
    with pytest.raises(Refused):
        fetch(fake)
    assert [str(r.url) for r in fake.requests] == [URL]


def chain(hops: int) -> dict[str, httpx2.Response]:
    pages = {f"https://clinic.example/{i}": redirect(f"https://clinic.example/{i + 1}") for i in range(hops)}
    return {**pages, f"https://clinic.example/{hops}": html("<p>end</p>")}


def test_max_redirects_are_followed_and_one_more_is_refused() -> None:
    assert fetch(site(chain(LIMITS.max_redirects)), "https://clinic.example/0").text == "end"
    fake = site(chain(LIMITS.max_redirects + 1))
    with pytest.raises(Refused):
        fetch(fake, "https://clinic.example/0")
    assert len(fake.requests) == LIMITS.max_redirects + 1


@pytest.mark.parametrize("kind", ["image/png", "application/json", "application/pdf", ""])
def test_a_body_that_is_not_text_is_refused(kind: str) -> None:
    with pytest.raises(Refused):
        fetch(site({URL: html(b"\x89PNG", kind=kind)}))


@pytest.mark.parametrize("fake", [
    site({URL: html("<p>gone</p>", status=404)}), site({URL: html("<p>err</p>", status=503)}),
    site({URL: httpx2.Response(302)}), raising(httpx2.ConnectError("refused")), raising(httpx2.ReadTimeout("slow"))])
def test_an_error_status_or_a_failed_connection_did_not_answer(fake: Fake) -> None:
    with pytest.raises(NoPage):
        fetch(fake)


def test_only_the_byte_cap_is_read_of_an_endless_body() -> None:
    async def endless() -> AsyncIterator[bytes]:
        while True:
            yield b"<p>" + b"a" * 1000 + b"</p>"

    fake = site({URL: httpx2.Response(200, content=endless(), headers={"content-type": "text/html"})})
    page = fetch(fake, limits=Limits(timeout_s=2, max_redirects=3, max_bytes=2500))
    assert page.bytes == 2500 and page.text.startswith("a" * 1000)


def test_a_page_slower_than_the_timeout_did_not_answer() -> None:
    async def slow() -> AsyncIterator[bytes]:
        yield b"<p>"
        await asyncio.sleep(5)
        yield b"</p>"

    fake = site({URL: httpx2.Response(200, content=slow(), headers={"content-type": "text/html"})})
    with pytest.raises(NoPage):
        fetch(fake, limits=Limits(timeout_s=0.05, max_redirects=3, max_bytes=1000))


def reply(fake: Fake, url: str = URL, resolver: Resolver | None = None) -> page_fetch.Reply:
    return asyncio.run(page_fetch.fetch_reply(fake.client(), url, LIMITS, resolver or Resolver()))


def test_a_reply_carries_the_final_status_the_headers_by_lowercase_name_and_the_title_of_a_page() -> None:
    answer = httpx2.Response(200, content=b"<title> Hours  here </title><p>x</p>",
                             headers=[("Content-Type", "text/html"), ("X-Frame-Options", "SAMEORIGIN")])
    got = reply(site({URL: answer}))
    assert (got.status, got.title) == (200, "Hours here") and got.headers["x-frame-options"] == "SAMEORIGIN"


def test_a_reply_to_a_challenge_is_its_status_and_headers_not_a_failure() -> None:
    answer = httpx2.Response(403, content=b"<title>Just a moment</title>", headers={"content-type": "text/html", "cf-mitigated": "challenge"})
    got = reply(site({URL: answer}))
    assert (got.status, got.title, got.headers["cf-mitigated"]) == (403, "", "challenge")


def test_a_reply_follows_redirects_and_reports_where_it_ended() -> None:
    other = "https://clinic.example/new"
    got = reply(site({URL: redirect(other), other: html("<title>New</title>")}))
    assert (got.status, got.title) == (200, "New")


def test_a_reply_that_is_not_html_has_no_title_and_its_body_is_not_read() -> None:
    assert reply(site({URL: html("<title>x</title>", kind="application/pdf")})).title == ""


def test_a_reply_keeps_the_request_forgery_boundary_and_no_answer_is_no_page() -> None:
    with pytest.raises(Refused):
        reply(site({URL: html("<p>x</p>")}), resolver=Resolver({"clinic.example": ["10.0.0.8"]}))
    with pytest.raises(NoPage):
        reply(raising(httpx2.ConnectError("down")))
