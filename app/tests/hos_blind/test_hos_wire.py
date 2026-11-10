"""`Wire`, the one capped GET behind both adapters (status to failure reason, the cap, redirects that are followed only
where asked, https only, once, with no header of the caller's), `json_rows`, and the tunables' parser."""

import json
from collections.abc import AsyncIterator

import httpx2
import pytest
from ashley.codehost import config
from ashley.codehost.host import CodeHostFailed
from ashley.codehost.model import Access, Reason
from ashley.codehost.wire import Wire, json_rows
from hos_support import all_logs, fields_of, go, log_text
from hos_forges_support import Forges

ACCESS = Access("gitlab", "https://a.test", "tok-SECRET-123")
HEADERS = {"X-Caller-Secret": "caller-secret-value", "Authorization": "Bearer tok-SECRET-123"}


def wire_for(f: Forges) -> Wire:
    return Wire(f.client(), 5.0)


async def reason_of(f: Forges, redirect: bool = False) -> Reason:
    wire = wire_for(f)
    try:
        await wire.get(ACCESS, "check", "", "https://a.test/x", {}, dict(HEADERS), 1000, redirect=redirect)
    except CodeHostFailed as e:
        return e.reason
    raise AssertionError("did not fail")


def serving(status: int, **headers: str) -> Forges:
    f = Forges()
    f.script.append(("a.test", "/", lambda r: httpx2.Response(status, content=b"body", headers=headers)))
    return f


@pytest.mark.parametrize("status, allowed", [(401, {"refused"}), (403, {"refused"}), (404, {"not_found"}),
                                              (500, {"unreachable", "unexpected"}), (502, {"unreachable", "unexpected"}),
                                              (503, {"unreachable", "unexpected"})])
def test_a_status_that_is_not_a_success_fails_with_its_reason(status: int, allowed: set[str]) -> None:
    async def scenario() -> None:
        assert await reason_of(serving(status)) in allowed

    go(scenario())


def test_a_success_returns_the_body_whole_when_it_fits() -> None:
    async def scenario() -> None:
        got = await wire_for(serving(200)).get(ACCESS, "check", "", "https://a.test/x", {}, dict(HEADERS), 1000)
        assert got.body == b"body" and got.cut is False

    go(scenario())


def test_a_body_over_the_cap_is_cut_at_the_cap_and_says_so() -> None:
    f = Forges()
    f.script.append(("a.test", "/", lambda r: httpx2.Response(200, content=b"0123456789" * 100)))

    async def scenario() -> None:
        got = await wire_for(f).get(ACCESS, "file", "p", "https://a.test/x", {}, dict(HEADERS), 25)
        assert got.body == b"0123456789" * 2 + b"01234" and got.cut is True
        exact = await wire_for(f).get(ACCESS, "file", "p", "https://a.test/x", {}, dict(HEADERS), 1000)
        assert len(exact.body) == 1000 and exact.cut is False

    go(scenario())


def test_a_body_that_arrives_in_pieces_is_cut_at_the_cap_and_says_the_rest_was_left() -> None:
    async def pieces() -> AsyncIterator[bytes]:
        for _ in range(10):
            yield b"0123456789"

    f = Forges()
    f.script.append(("a.test", "/", lambda r: httpx2.Response(200, content=pieces())))

    async def scenario() -> None:
        for cap, cut in ((20, True), (25, True), (99, True), (100, False), (101, False)):
            got = await wire_for(f).get(ACCESS, "file", "p", "https://a.test/x", {}, dict(HEADERS), cap)
            assert (len(got.body), got.cut) == (min(cap, 100), cut), cap

    go(scenario())


def test_the_call_is_given_the_configured_timeout() -> None:
    f = Forges()
    seen: list[dict[str, object]] = []

    def answer(r: httpx2.Request) -> httpx2.Response:
        seen.append(dict(r.extensions["timeout"]))
        return httpx2.Response(200, content=b"ok")

    f.script.append(("a.test", "/", answer))

    async def scenario() -> None:
        await Wire(f.client(), 7.5).get(ACCESS, "check", "", "https://a.test/x", {}, dict(HEADERS), 100)

    go(scenario())
    assert seen and set(seen[0].values()) == {7.5}


def test_the_caller_headers_and_params_are_sent() -> None:
    f = serving(200)

    async def scenario() -> None:
        await wire_for(f).get(ACCESS, "check", "", "https://a.test/x", {"per_page": 7, "q": "a b&c"}, dict(HEADERS), 100)

    go(scenario())
    (seen,) = f.seen
    assert seen.headers["x-caller-secret"] == "caller-secret-value" and seen.query == {"per_page": ["7"], "q": ["a b&c"]}


def test_no_redirect_is_followed_unless_asked_for() -> None:
    f = serving(302, location="https://b.test/next")

    async def scenario() -> None:
        assert await reason_of(f) in ("unreachable", "unexpected", "not_found", "refused")

    go(scenario())
    assert f.to("b.test") == []


def test_an_asked_for_redirect_is_followed_once_to_https_with_none_of_the_callers_headers() -> None:
    f = serving(302, location="https://b.test/next?sig=abc")
    f.script.append(("b.test", "/", lambda r: httpx2.Response(200, content=b"zipbytes")))

    async def scenario() -> None:
        got = await wire_for(f).get(ACCESS, "archive", "p", "https://a.test/x", {}, dict(HEADERS), 1000, redirect=True)
        assert got.body == b"zipbytes"

    go(scenario())
    (hop,) = f.to("b.test")
    assert not {"authorization", "private-token", "x-caller-secret", "cookie"} & set(hop.headers)
    assert "tok-SECRET-123" not in hop.url_text() + str(hop.headers)
    assert len(f.to("a.test")) == 1


@pytest.mark.parametrize("target", ["http://b.test/next", "ftp://b.test/next", "file:///etc/passwd", "//b.test/next",
                                    "/relative"])
def test_a_redirect_that_is_not_https_is_refused_and_not_requested(target: str) -> None:
    f = serving(302, location=target)
    f.script.append(("b.test", "/", lambda r: httpx2.Response(200, content=b"zipbytes")))

    async def scenario() -> None:
        await reason_of(f, redirect=True)

    go(scenario())
    assert f.to("b.test") == [] and len(f.seen) == 1


def test_a_second_redirect_is_not_followed() -> None:
    f = serving(302, location="https://b.test/next")
    f.script.append(("b.test", "/", lambda r: httpx2.Response(302, headers={"location": "https://c.test/more"})))

    async def scenario() -> None:
        await reason_of(f, redirect=True)

    go(scenario())
    assert f.to("c.test") == [] and len(f.to("b.test")) == 1


def test_a_redirect_with_no_location_is_a_failure() -> None:
    f = Forges()
    f.script.append(("a.test", "/", lambda r: httpx2.Response(302)))

    async def scenario() -> None:
        await reason_of(f, redirect=True)

    go(scenario())


def test_a_connection_that_fails_or_times_out_is_unreachable_and_logs_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)
    for kind in ("down", "slow"):
        f = Forges()
        getattr(f, kind).add("a.test")

        async def scenario() -> None:
            assert await reason_of(f) == "unreachable"

        go(scenario())
    assert "tok-SECRET-123" not in log_text(caplog) and "caller-secret-value" not in log_text(caplog)


def test_the_one_log_line_has_the_forge_call_project_status_bytes_and_duration(caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)

    async def scenario() -> None:
        await wire_for(serving(200)).get(ACCESS, "tree", "grp/proj", "https://a.test/secret/path?x=1", {}, dict(HEADERS), 100)

    go(scenario())
    (line,) = fields_of(caplog, "codehost.get")
    assert (line["forge"], line["call"], line["project"], line["status"], line["bytes"]) == ("gitlab", "tree",
                                                                                          "grp/proj", 200, 4)
    assert "duration_ms" in line
    assert "secret/path" not in log_text(caplog, "ashley") and "tok-SECRET-123" not in log_text(caplog)


# --- json_rows ----------------------------------------------------------------------------------------------------


def test_json_rows_are_the_objects_of_a_list() -> None:
    assert json_rows(b"[]") == []
    assert json_rows(json.dumps([{"a": 1}, {"b": [2]}]).encode()) == [{"a": 1}, {"b": [2]}]


@pytest.mark.parametrize("body", [b'{"a": 1}', b"null", b'"text"', b"3", b"[1, 2]", b'[{"a": 1}, "x"]', b"[null]", b"",
                                  b"<html></html>", b"[{", b"\xff\xfe"])
def test_json_rows_of_any_other_shape_is_unexpected(body: bytes) -> None:
    with pytest.raises(CodeHostFailed) as e:
        json_rows(body)
    assert e.value.reason == "unexpected"


# --- the tunables -------------------------------------------------------------------------------------------------

GOOD = {"timeout_s": 3.5, "projects_max": 10, "tree_max": 20, "read_bytes": 1000, "snapshot_max_bytes": 5000}


def test_the_shipped_tunables_load_and_a_page_fits_the_forges() -> None:
    c = config.load()
    assert c.timeout_s > 0 and 0 < c.projects_max <= config.PAGE_MAX and 0 < c.tree_max <= config.PAGE_MAX
    assert c.read_bytes > 0 and c.snapshot_max_bytes > 0


def test_parse_reads_every_key() -> None:
    c = config.parse(GOOD)
    assert (c.timeout_s, c.projects_max, c.tree_max, c.read_bytes, c.snapshot_max_bytes) == tuple(
        GOOD.values())


def test_parse_takes_a_page_at_the_page_size() -> None:
    assert config.parse({**GOOD, "projects_max": config.PAGE_MAX, "tree_max": config.PAGE_MAX}).tree_max == config.PAGE_MAX


@pytest.mark.parametrize("bad", [
    {k: v for k, v in GOOD.items() if k != "tree_max"},
    {**GOOD, "extra": 1},
    {**GOOD, "projects_max": 0}, {**GOOD, "projects_max": -1}, {**GOOD, "projects_max": 1.5}, {**GOOD, "projects_max": "5"},
    {**GOOD, "projects_max": config.PAGE_MAX + 1}, {**GOOD, "tree_max": config.PAGE_MAX + 1},
    {**GOOD, "read_bytes": 0}, {**GOOD, "snapshot_max_bytes": 0},
    {**GOOD, "timeout_s": 0}, {**GOOD, "timeout_s": -1.0}, {**GOOD, "timeout_s": "3"}, {**GOOD, "timeout_s": None},
    [], None, "x", 3,
])
def test_parse_refuses_what_is_not_the_tunables(bad: object) -> None:
    with pytest.raises(ValueError):
        config.parse(bad)
