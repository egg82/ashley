"""`driver.py`, the program a browser session's pod runs, against a fake page: a snapshot names each element by a
reference; an action on a reference is checked against a fresh snapshot first and refused when the element is gone or
changed; a secret field refuses text; the session ends at its time and action caps; and the HTTP side wants the token."""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from ashley.looks import driver

LIMITS = {"width": 1280, "height": 800, "session_max_s": 100, "session_max_actions": 3, "session_step_s": 7,
          "snapshot_nodes": 50, "snapshot_name_chars": 40}
PAGE = [{"role": "textbox", "name": "Email"}, {"role": "textbox", "name": "Password", "secret": True},
        {"role": "button", "name": "Go"}, {"role": "button", "name": "Go"}]


class FakeError(Exception):
    pass


class FakeTimeout(FakeError):
    pass


class FakeApi:
    Error = FakeError
    TimeoutError = FakeTimeout


class FakeElement:
    def __init__(self, page: "FakePage", selector: str) -> None:
        self.page, self.selector = page, selector

    def _do(self, what: str, **kwargs: Any) -> None:
        if self.page.fail is not None:
            raise self.page.fail
        self.page.done.append((what, self.selector, kwargs))

    def click(self, timeout: int) -> None:
        self._do("click", timeout=timeout)

    def fill(self, text: str, timeout: int) -> None:
        self._do("fill", text=text, timeout=timeout)

    def press(self, key: str, timeout: int) -> None:
        self._do("press", key=key)

    def select_option(self, label: str, timeout: int) -> None:
        self._do("select", label=label)


class FakePage:
    url = "https://shop.example/cart"

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = PAGE
        self.done: list[tuple[str, str, dict[str, Any]]] = []
        self.opened: list[tuple[str, int, str]] = []
        self.fail: Exception | None = None
        self.asked: list[dict[str, int]] = []

    def evaluate(self, script: str, limits: dict[str, int]) -> dict[str, Any]:
        assert script == driver.SNAPSHOT_JS
        self.asked.append(limits)
        return {"nodes": self.nodes, "cut": False}

    def title(self) -> str:
        return "Cart"

    def locator(self, selector: str) -> FakeElement:
        return FakeElement(self, selector)

    def goto(self, url: str, timeout: int, wait_until: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.opened.append((url, timeout, wait_until))


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def session(page: FakePage | None = None, clock: Clock | None = None) -> tuple[driver.Session, FakePage, Clock]:
    page, clock = page or FakePage(), clock or Clock()
    return driver.Session(FakeApi(), page, LIMITS, clock), page, clock


def test_a_snapshot_names_each_element_by_reference_with_the_limits_the_pod_was_given() -> None:
    one, page, _ = session()
    status, answer = one.handle("/snapshot", {})
    assert status == 200
    assert [(n["ref"], n["role"], n["name"]) for n in answer["nodes"]] == [
        ("e0", "textbox", "Email"), ("e1", "textbox", "Password"), ("e2", "button", "Go"), ("e3", "button", "Go")]
    assert answer["nodes"][1]["secret"] is True
    assert (answer["title"], answer["cut"], answer["seconds_left"], answer["actions_left"]) == ("Cart", False, 100, 3)
    assert page.asked == [{"nodes": 50, "name": 40}]


def test_a_click_is_aimed_at_the_element_found_again_in_a_fresh_snapshot_not_at_the_old_index() -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    page.nodes = [{"role": "banner", "name": "Sale"}, *PAGE]
    status, answer = one.handle("/act", {"action": "click", "ref": "e3"})
    assert status == 200 and answer["actions_left"] == 2
    assert page.done == [("click", '[data-ashley-ref="4"]', {"timeout": 7000})]


def test_an_element_that_changed_or_went_is_stale_and_nothing_is_done() -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    page.nodes = [{"role": "button", "name": "Stop"}]
    assert one.handle("/act", {"action": "click", "ref": "e2"}) == (400, {"reason": "stale_ref"})
    assert page.done == []
    assert one.counts()["actions_left"] == 3


@pytest.mark.parametrize("ref", ["e9", "e-1", "3", None, "e1 "])
def test_a_ref_the_snapshot_never_gave_is_refused(ref: object) -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    status, answer = one.handle("/act", {"action": "click", "ref": ref})
    assert status == 400 and answer["reason"] in ("no_such_ref", "bad_request")
    assert page.done == []


def test_a_secret_field_refuses_text_and_costs_no_action() -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    assert one.handle("/act", {"action": "type", "ref": "e1", "text": "hunter2"}) == (400, {"reason": "secret_field"})
    assert page.done == [] and one.counts()["actions_left"] == 3


def test_type_fills_and_submits_and_select_picks_an_option_by_name() -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    assert one.handle("/act", {"action": "type", "ref": "e0", "text": "a@b.example", "submit": True})[0] == 200
    assert one.handle("/act", {"action": "select", "ref": "e2", "value": "Large"})[0] == 200
    assert [d[0] for d in page.done] == ["fill", "press", "select"]
    assert page.done[0][2]["text"] == "a@b.example" and page.done[2][2]["label"] == "Large"


@pytest.mark.parametrize("body", [{"action": "type", "ref": "e0"}, {"action": "select", "ref": "e0", "value": 3},
                                  {"action": "hover", "ref": "e0"}, {"action": "navigate"},
                                  {"action": "navigate", "url": "http://plain.example"},
                                  {"action": "navigate", "url": "file:///etc/passwd"}])
def test_a_malformed_step_is_refused_before_anything_happens(body: dict[str, Any]) -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    assert one.handle("/act", body) == (400, {"reason": "bad_request"})
    assert page.done == [] and page.opened == [] and one.counts()["actions_left"] == 3


def test_navigate_opens_an_https_page_and_counts_as_an_action() -> None:
    one, page, _ = session()
    assert one.handle("/act", {"action": "navigate", "url": "https://shop.example/"})[0] == 200
    assert page.opened == [("https://shop.example/", 7000, "domcontentloaded")]
    assert one.counts()["actions_left"] == 2


def test_the_browsers_own_failures_are_a_reason_not_a_crash() -> None:
    one, page, _ = session()
    one.handle("/snapshot", {})
    page.fail = FakeTimeout()
    assert one.handle("/act", {"action": "click", "ref": "e2"}) == (400, {"reason": "page_timeout"})
    page.fail = FakeError()
    assert one.handle("/act", {"action": "click", "ref": "e2"}) == (400, {"reason": "page_error"})


def test_past_the_action_cap_an_act_ends_the_session_but_a_snapshot_still_shows_the_result() -> None:
    one, _, _ = session()
    one.handle("/snapshot", {})
    for _ in range(3):
        assert one.handle("/act", {"action": "click", "ref": "e2"})[0] == 200
    assert one.handle("/snapshot", {})[0] == 200
    assert one.handle("/act", {"action": "click", "ref": "e2"}) == (410, {"ended": "actions"})


def test_past_the_time_cap_every_request_ends_the_session() -> None:
    one, _, clock = session()
    clock.now = 99.0
    assert one.handle("/snapshot", {})[1]["seconds_left"] == 1
    clock.now = 100.0
    assert one.handle("/snapshot", {}) == (410, {"ended": "time"})
    assert one.handle("/act", {"action": "navigate", "url": "https://shop.example/"}) == (410, {"ended": "time"})


def test_the_snapshot_script_marks_what_it_names_so_the_action_finds_it() -> None:
    assert "data-ashley-ref" in driver.SNAPSHOT_JS and "limits.nodes" in driver.SNAPSHOT_JS
    assert "type === 'password'" in driver.SNAPSHOT_JS and "cc-" in driver.SNAPSHOT_JS


@pytest.fixture
def served() -> Iterator[tuple[str, Clock, threading.Event]]:
    one, _, clock = session()
    ended = threading.Event()
    server = driver.HTTPServer(("127.0.0.1", 0), driver.handler(one, "tok", ended.set))
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", clock, ended
    server.shutdown()
    server.server_close()


def post(base: str, path: str, token: str | None, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(base + path, json.dumps(body).encode(), {"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=3) as got:
            return got.status, json.loads(got.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_requests_need_the_token_but_health_does_not(served: tuple[str, Clock, threading.Event]) -> None:
    base, _, _ = served
    assert post(base, "/snapshot", None, {})[0] == 401
    assert post(base, "/snapshot", "wrong", {})[0] == 401
    status, answer = post(base, "/snapshot", "tok", {})
    assert status == 200 and len(answer["nodes"]) == 4
    assert urllib.request.urlopen(base + "/healthz", timeout=3).status == 200
    assert post(base, "/elsewhere", "tok", {})[0] == 404


def test_a_request_answered_gone_stops_the_server(served: tuple[str, Clock, threading.Event]) -> None:
    base, clock, ended = served
    clock.now = 1000.0
    assert post(base, "/snapshot", "tok", {}) == (410, {"ended": "time"})
    assert ended.wait(2)
