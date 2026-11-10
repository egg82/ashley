"""The warm pod opens only addresses under the app's look page (`ASHLEY_LOOK_PREFIX`): any other host, scheme, path or
trick that a browser would resolve to somewhere else is refused before it reaches the browser."""

import pytest
from warm_blind_support import PREFIX, pod_server

INSIDE = [
    PREFIX + "tok",
    PREFIX + "tok?piece=3",
    PREFIX + "a.b-c_d~e",
    PREFIX + "a/b",
    PREFIX + "tok%2Fmore",
    PREFIX + "x" * 300,
]

OUTSIDE = [
    "http://evil.example/look/tok",
    "https://ashley.ashley.svc:8080/look/tok",
    "http://ashley.ashley.svc:9090/look/tok",
    "http://ashley.ashley.svc/look/tok",
    "http://ashley.ashley.svc:8080/api/look/tok",
    "http://ashley.ashley.svc:8080/lookup/tok",
    "http://ashley.ashley.svc:8080/look",
    "http://ashley.ashley.svc:8080/",
    "http://ashley.ashley.svc:8080",
    "http://ashley.ashley.svc:8080/Look/tok",
    "http://ashley.ashley.svc:8080/api/health",
    "HTTP://ASHLEY.ASHLEY.SVC:8080/look/tok/../../api/health",
    "http://ashley.ashley.svc:8080/look\\..\\api/health",
    "http://ashley.ashley.svc:8080@evil.example/look/tok",
    "http://ashley.ashley.svc:8080:80/look/tok",
    "http://ashley.ashley.svc:8080.evil.example/look/tok",
    "http://ashley.ashley.svc.evil.example:8080/look/tok",
    "http://evil.example/http://ashley.ashley.svc:8080/look/tok",
    "http://evil.example/?http://ashley.ashley.svc:8080/look/tok",
    "http://evil.example/#http://ashley.ashley.svc:8080/look/tok",
    "//evil.example/look/tok",
    "/look/tok",
    "look/tok",
    "file:///etc/passwd",
    "file:///look/tok",
    "javascript:alert(1)",
    "data:text/html,hi",
    "about:blank",
    "chrome://version",
    "ftp://ashley.ashley.svc:8080/look/tok",
    "ws://ashley.ashley.svc:8080/look/tok",
    " http://ashley.ashley.svc:8080/look/../x",
    "",
    " ",
]

TRAVERSAL = [
    "http://ashley.ashley.svc:8080/look/../api/health",
    "http://ashley.ashley.svc:8080/look/tok/../../api/health",
    "http://ashley.ashley.svc:8080/look/%2e%2e/api/health",
    "http://ashley.ashley.svc:8080/look/%2E%2E/api/health",
    "http://ashley.ashley.svc:8080/look/.%2e/api/health",
    "http://ashley.ashley.svc:8080/look/%2e./api/health",
    "http://ashley.ashley.svc:8080/look/..\\api/health",
    "http://ashley.ashley.svc:8080/look/.\t./api/health",
    "http://ashley.ashley.svc:8080/look/.\n./api/health",
    "http://ashley.ashley.svc:8080/look/tok%00/../../x",
]


@pytest.mark.parametrize("url", INSIDE)
def test_an_address_under_the_look_page_is_opened(url: str) -> None:
    with pod_server() as pod:
        r = pod.look(url)
    assert r.status_code == 200
    assert pod.seen == [url]


@pytest.mark.parametrize("url", OUTSIDE)
def test_an_address_elsewhere_is_refused_before_the_browser(url: str) -> None:
    with pod_server() as pod:
        r = pod.look(url)
    assert 400 <= r.status_code < 500, r.status_code
    assert pod.seen == [] and pod.jobs.empty()


@pytest.mark.parametrize("url", TRAVERSAL)
def test_an_address_that_a_browser_resolves_out_of_the_look_page_is_refused(url: str) -> None:
    with pod_server() as pod:
        r = pod.look(url)
    assert 400 <= r.status_code < 500, r.status_code
    assert pod.seen == []


def test_the_prefix_is_whatever_the_pod_was_started_with() -> None:
    other = "http://app.other.test:81/look/"
    with pod_server(prefix=other) as pod:
        assert pod.look(PREFIX + "tok").status_code >= 400
        assert pod.look(other + "tok").status_code == 200
    assert pod.seen == [other + "tok"]


def test_a_refused_address_is_not_echoed_back() -> None:
    with pod_server() as pod:
        r = pod.look("http://evil.example/SECRETzq")
    assert "SECRETzq" not in r.text
