"""The fetch behind `read_page`: the public-address rule on real literals (a host that resolves to anything else, or to
a mix, is refused before any request), https only, redirects followed by hand and checked at every hop, the byte cap,
the content-type rule, and a page that does not answer."""

import httpx2
import pytest
from read_page_contract_support import (NO_ANSWER, NOT_READABLE, PUBLIC, SITES, Chunks, Dns, Responder, cfg, failing,
                                        fetch, install_dns, ok_text, page, redirect, streamed)

OPEN = "<p>Open 9-5</p>"
MARK = "zqBODY6620"
PRIVATE = ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fd00::1", "100.64.0.1"]
SECOND = "https://site9.test/elsewhere"


@pytest.fixture(autouse=True)
def dns(monkeypatch: pytest.MonkeyPatch) -> Dns:
    return install_dns(monkeypatch)


@pytest.mark.parametrize("address", PRIVATE)
def test_a_host_that_resolves_to_a_non_public_address_is_refused_before_any_request(address: str, dns: Dns) -> None:
    dns.table["site1.test"] = [address]
    result, net = fetch(page(OPEN + MARK))
    assert (result.is_error, result.content) == (True, NOT_READABLE)
    assert net.hits == [] and dns.asked.count("site1.test") >= 1, "the fake resolver was asked and nothing connected"


@pytest.mark.parametrize("answer", [[PUBLIC, "10.0.0.5"], ["10.0.0.5", PUBLIC], [PUBLIC, PUBLIC, "169.254.169.254"],
                                    [PUBLIC, "fd00::1"], ["2606:4700:4700::1111", "127.0.0.1"]])
def test_a_mixed_answer_with_any_non_public_address_is_refused(answer: list[str], dns: Dns) -> None:
    dns.table["site1.test"] = answer
    result, net = fetch(page(OPEN))
    assert (result.is_error, result.content) == (True, NOT_READABLE) and net.hits == []


@pytest.mark.parametrize("answer", [[PUBLIC], ["2606:4700:4700::1111"], [PUBLIC, "2606:4700:4700::1111"]])
def test_an_all_public_answer_is_read(answer: list[str], dns: Dns) -> None:
    dns.table["site1.test"] = answer
    result, net = fetch(page(OPEN))
    assert ok_text(result).strip() == "Open 9-5" and len(net.hits) == 1 and dns.asked.count("site1.test") >= 1


@pytest.mark.parametrize("url", ["https://127.0.0.1/", "https://10.0.0.5/menu", "https://[::1]/", "https://[fd00::1]/",
                                 "https://169.254.169.254/latest/meta-data/"])
def test_a_literal_non_public_address_in_the_result_is_refused(url: str) -> None:
    result, net = fetch(page(OPEN), url=url)
    assert (result.is_error, result.content) == (True, NOT_READABLE) and net.hits == []


def test_a_literal_public_address_in_the_result_is_read() -> None:
    result, net = fetch(page(OPEN), url=f"https://{PUBLIC}/hours")
    assert ok_text(result).strip() == "Open 9-5" and len(net.hits) == 1


@pytest.mark.parametrize("url", ["http://site1.test/page1", "ftp://site1.test/page1", "file:///etc/passwd"])
def test_a_scheme_other_than_https_is_refused_without_a_request(url: str, dns: Dns) -> None:
    result, net = fetch(page(OPEN), url=url)
    assert (result.is_error, result.content) == (True, NOT_READABLE) and net.hits == []


def test_a_redirect_to_http_is_refused_and_never_requested() -> None:
    result, net = fetch(redirect("http://site9.test/elsewhere"), more={"site9.test": page(OPEN + MARK)})
    assert (result.is_error, result.content) == (True, NOT_READABLE)
    assert net.hosts == ["site1.test"] and all(r.url.scheme == "https" for r in net.hits)


@pytest.mark.parametrize("target", ["https://intranet.test/admin", "https://169.254.169.254/latest/meta-data/",
                                    "https://[::1]:8123/api"])
def test_a_redirect_to_a_non_public_host_is_refused_and_never_requested(target: str, dns: Dns) -> None:
    dns.table["intranet.test"] = ["10.0.0.5"]
    result, net = fetch(redirect(target), more={"intranet.test": page(OPEN + MARK)})
    assert (result.is_error, result.content) == (True, NOT_READABLE)
    assert net.hosts == ["site1.test"], "control: the first hop was fetched, the second was not"
    assert "site1.test" in dns.asked


def test_a_redirect_to_a_public_host_is_followed_and_each_host_is_resolved() -> None:
    result, net = fetch(redirect(SECOND), more={"site9.test": page("<p>moved here</p>")})
    assert ok_text(result).strip() == "moved here" and net.hosts == ["site1.test", "site9.test"]


def test_a_relative_redirect_stays_on_the_host() -> None:
    moved, there = redirect("/new/path?x=1"), page("<p>moved here</p>")

    def site(request: httpx2.Request) -> httpx2.Response:
        return (there if request.url.path == "/new/path" else moved)(request)

    result, net = fetch(site)
    assert [str(r.url) for r in net.hits] == [SITES[0], "https://site1.test/new/path?x=1"] and result.is_error is False


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_redirect_status_is_followed(status: int) -> None:
    result, net = fetch(redirect(SECOND, status), more={"site9.test": page("<p>moved here</p>")})
    assert ok_text(result).strip() == "moved here" and len(net.hits) == 2


def chain(hops: int) -> dict[str, Responder]:
    """With site1.test's own redirect to site2.test, `hops` redirects in all, then site<hops+1>.test answers a page."""
    out = {f"site{i}.test": redirect(f"https://site{i + 1}.test/") for i in range(2, hops + 1)}
    return out | {f"site{hops + 1}.test": page("<p>end of chain</p>")}


@pytest.mark.parametrize(("limit", "redirects", "reads"), [(3, 3, True), (3, 4, False), (1, 1, True), (1, 2, False),
                                                         (5, 5, True), (5, 6, False)])
def test_at_most_max_redirects_redirects_are_followed(limit: int, redirects: int, reads: bool) -> None:
    more = chain(redirects)
    result, net = fetch(redirect("https://site2.test/"), config=cfg(max_redirects=limit), more=more)
    if reads:
        assert ok_text(result).strip() == "end of chain" and len(net.hits) == redirects + 1
    else:
        assert (result.is_error, result.content) == (True, NOT_READABLE)
        assert len(net.hits) == limit + 1, "the redirect after the limit was not followed"


def test_a_redirect_loop_ends_refused() -> None:
    result, net = fetch(redirect(SITES[0]))
    assert (result.is_error, result.content) == (True, NOT_READABLE) and len(net.hits) == 4


@pytest.mark.parametrize("status", [404, 403, 410, 429, 500, 502, 503])
def test_a_non_2xx_page_did_not_answer(status: int) -> None:
    result, net = fetch(page("<p>" + MARK + "</p>", status))
    assert (result.is_error, result.content) == (True, NO_ANSWER) and len(net.hits) == 1


def test_a_non_2xx_after_a_redirect_did_not_answer() -> None:
    result, _ = fetch(redirect(SECOND), more={"site9.test": page("gone", 404)})
    assert (result.is_error, result.content) == (True, NO_ANSWER)


@pytest.mark.parametrize("error", [httpx2.ReadTimeout("t"), httpx2.ConnectTimeout("t"), httpx2.ConnectError("c"),
                                   httpx2.ReadError("r"), httpx2.RemoteProtocolError("p")])
def test_a_timeout_or_connection_error_did_not_answer(error: Exception) -> None:
    result, net = fetch(failing(error))
    assert (result.is_error, result.content) == (True, NO_ANSWER) and len(net.hits) == 1


@pytest.mark.parametrize("ctype", ["text/html", "text/html; charset=utf-8", "text/plain", "text/plain; charset=utf-8"])
def test_html_and_plain_text_are_read(ctype: str) -> None:
    result, _ = fetch(page("Hours: 9-5 daily", ctype=ctype))
    assert ok_text(result).strip() == "Hours: 9-5 daily"


@pytest.mark.parametrize("ctype", ["application/pdf", "image/png", "application/json", "application/octet-stream",
                                   "text/css", "text/javascript", "video/mp4"])
def test_any_other_content_type_is_refused_and_its_body_never_returned(ctype: str) -> None:
    result, net = fetch(page(f"<p>{MARK}</p>", ctype=ctype))
    assert (result.is_error, result.content) == (True, NOT_READABLE) and len(net.hits) == 1


def test_non_ascii_text_survives_html_and_plain() -> None:
    assert ok_text(fetch(page("<p>Café — open</p>"))[0]).strip() == "Café — open"
    plain = ok_text(fetch(page("Café — open", ctype="text/plain; charset=utf-8"))[0])
    assert plain.strip() == "Café — open"


def test_only_page_bytes_are_read_from_the_body() -> None:
    cap = cfg(page_bytes=1000)
    text = ok_text(fetch(page(b"a" * 1500 + b"ENDMARK", ctype="text/plain"), config=cap)[0])
    assert text.strip() == "a" * 1000
    assert ok_text(fetch(page(b"a" * 1000, ctype="text/plain"), config=cap)[0]).strip() == "a" * 1000
    assert ok_text(fetch(page(b"a" * 999, ctype="text/plain"), config=cap)[0]).strip() == "a" * 999


def test_the_body_is_streamed_and_reading_stops_at_the_cap() -> None:
    stream = Chunks(b"b" * 100, 1000)
    text = ok_text(fetch(streamed(stream), config=cfg(page_bytes=1000))[0])
    assert text.strip() == "b" * 1000
    assert stream.pulled <= 12, "ten chunks make the cap; the other 990 are never pulled"


def test_a_cut_through_a_multibyte_character_or_a_tag_still_reads() -> None:
    cut = cfg(page_bytes=1001)
    text = ok_text(fetch(page("é" * 600, ctype="text/plain"), config=cut)[0])
    assert text.startswith("ééé") and len(text) <= 1001
    html = ok_text(fetch(page("<p>before</p><p>" + "z" * 990 + "<a href='/x'>link</a></p>"), config=cut)[0])
    assert "before" in html and "zzz" in html
