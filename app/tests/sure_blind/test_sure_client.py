"""The port to Sure (`sure.client`, `sure.check`): what is asked and with what, what each failure is called, and that
the key stays out of every exception and log line."""

import asyncio
import logging
import traceback

import httpx2
import pytest
from ashley import logs, services
from ashley.sure.check import accounts_seen
from ashley.sure.client import HttpSure, Sure, SureFailed, base_url
from money_support import BASE, KEY, FakeSure


def get(fake: FakeSure, path: str = "/api/v1/accounts", params: dict[str, str | int] | None = None,
        key: str = KEY, base: str = BASE) -> object:
    return asyncio.run(fake.client().get(base, key, path, params or {}))


def reason_of(fake: FakeSure, key: str = KEY) -> SureFailed:
    with pytest.raises(SureFailed) as got:
        get(fake, key=key)
    return got.value


@pytest.mark.parametrize("text", ["https://money.example", "https://money.example/", "https://money.example/sure",
                                  "https://money.example:8443", "https://money.example/sure/"])
def test_base_url_accepts_https_with_a_host(text: str) -> None:
    got = base_url(text)
    assert got is not None and got.startswith("https://money.example") and not got.endswith("/")


@pytest.mark.parametrize("text", ["", "money.example", "http://money.example", "ftp://money.example", "https://",
                                  "https:///x", "https://u:p@money.example", "https://u@money.example",
                                  "https://money.example/?a=1", "https://money.example/#frag",
                                  "https://money.example?a=1"])
def test_base_url_refuses_the_rest(text: str) -> None:
    assert base_url(text) is None


def test_a_get_asks_the_path_with_params_and_the_key_header() -> None:
    fake = FakeSure()
    assert get(fake, "/api/v1/accounts", {"per_page": 3, "q": "x y"}) == fake.answers["/api/v1/accounts"]
    [(path, params, key)] = fake.seen
    assert (path, params, key) == ("/api/v1/accounts", {"per_page": "3", "q": "x y"}, KEY)


def test_the_base_path_is_kept() -> None:
    seen: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url.path))
        return httpx2.Response(200, json={})

    http = HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), 5)
    asyncio.run(http.get("https://m.test/sure", KEY, "/api/v1/accounts", {}))
    assert seen == ["/sure/api/v1/accounts"]


def test_only_reads_are_made() -> None:
    methods: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        methods.append(request.method)
        return httpx2.Response(200, json={})

    http = HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), 5)
    asyncio.run(http.get(BASE, KEY, "/api/v1/accounts", {}))
    assert methods == ["GET"]


@pytest.mark.parametrize(("status", "reason"), [(401, "refused"), (403, "refused"), (500, "unreachable"),
                                                (502, "unreachable"), (503, "unreachable"), (301, "unreachable"),
                                                (302, "unreachable"), (307, "unreachable"), (404, "not_sure")])
def test_each_status_is_a_typed_reason(status: int, reason: str) -> None:
    assert reason_of(FakeSure(status=status)).reason == reason


def test_a_page_that_is_not_json_is_not_sure() -> None:
    assert reason_of(FakeSure(raw=b"<html>sign in</html>")).reason == "not_sure"


def test_a_wrong_key_is_key_refused() -> None:
    assert reason_of(FakeSure(), key="not-it").reason == "refused"


def test_nothing_answering_is_unreachable() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow")

    for handler in (down, slow):
        http = HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), 5)
        with pytest.raises(SureFailed) as got:
            asyncio.run(http.get(BASE, KEY, "/api/v1/accounts", {}))
        assert got.value.reason == "unreachable"


def test_a_redirect_is_not_followed_so_the_key_goes_nowhere_else() -> None:
    hosts: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        hosts.append(request.url.host)
        return httpx2.Response(302, headers={"location": "https://elsewhere.test/api/v1/accounts"})

    http = HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handle), follow_redirects=False), 5)
    with pytest.raises(SureFailed):
        asyncio.run(http.get(BASE, KEY, "/api/v1/accounts", {}))
    assert hosts == ["money.test"]


@pytest.mark.parametrize("fake", [FakeSure(status=401), FakeSure(status=500), FakeSure(raw=b"<html>"),
                                  FakeSure(key="other")])
def test_the_key_is_in_no_exception_text(fake: FakeSure) -> None:
    err = reason_of(fake)
    assert KEY not in str(err) and KEY not in repr(err) and KEY not in repr(err.args)


@pytest.mark.parametrize("fake", [FakeSure(status=401), FakeSure(status=500), FakeSure(raw=b"<html>")])
def test_the_key_is_in_no_rendered_traceback(fake: FakeSure) -> None:
    err = reason_of(fake)
    assert KEY not in "".join(traceback.format_exception(err))


def test_a_transport_failure_carries_no_key_in_its_traceback() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    http = HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(down)), 5)
    with pytest.raises(SureFailed) as got:
        asyncio.run(http.get(BASE, KEY, "/api/v1/accounts", {}))
    assert KEY not in "".join(traceback.format_exception(got.value))


def test_the_key_is_in_no_log_line(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    logs.setup()
    capsys.readouterr()
    with caplog.at_level(logging.DEBUG):
        get(FakeSure(), params={"q": "secret-search-words"})
        for fake in (FakeSure(status=401), FakeSure(status=500)):
            reason_of(fake)
    out = capsys.readouterr()
    text = out.out + out.err + caplog.text
    assert "sure.get" in text
    assert KEY not in text and "secret-search-words" not in text


def test_accounts_seen_counts_the_accounts_and_asks_for_the_key_once() -> None:
    fake = FakeSure()
    services.register(Sure, fake.client())
    assert asyncio.run(accounts_seen(BASE, KEY)) == 2
    assert len(fake.seen) == 1 and fake.seen[0][2] == KEY and fake.seen[0][0] == "/api/v1/accounts"


@pytest.mark.parametrize(("fake", "reason"), [(FakeSure(status=401), "refused"), (FakeSure(status=502), "unreachable"),
                                              (FakeSure(raw=b"<html>"), "not_sure"),
                                              (FakeSure(answers={"/api/v1/accounts": {"hello": 1}}), "not_sure")])
def test_accounts_seen_fails_with_the_reason(fake: FakeSure, reason: str) -> None:
    services.register(Sure, fake.client())
    with pytest.raises(SureFailed) as got:
        asyncio.run(accounts_seen(BASE, KEY))
    assert got.value.reason == reason
