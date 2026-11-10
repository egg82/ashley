"""The page browser: `shooter.py`'s read mode against a fake Playwright prints what the browser was given for a public
page; the Kubernetes browser asks for a look pod that also carries the fetch label (public HTTPS) and never the warm
label, and reads the page back from the pod's log, checked, deleting the pod however it ends."""

import asyncio
import base64
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from ashley.looks import config, shooter
from ashley.looks.browser import BrowseUnavailable
from ashley.looks.kubernetes import FAILED, SHOOTER
from ashley.looks.kubernetes_browser import READ, KubernetesBrowser, browsed
from ashley.looks.pod_spec import LABEL, WARM_LABEL
from ashley.runs.media_pod import FETCH_LABEL
from sandbox_support import Clock, FakeKube, Script

CONFIG = config.load()
IMAGE = "mcr.example/browser@sha256:" + "b" * 64
URL = "https://recipes.example/mash"
PAGE = "<html><head><title>Mash</title></head><body>café</body></html>"


class FakeError(Exception):
    pass


class FakeTimeout(FakeError):
    pass


class FakeResponse:
    status = 403
    headers = {"content-type": "text/html; charset=utf-8"}


class FakePage:
    def __init__(self, timeout: bool) -> None:
        self.timeout = timeout
        self.opened: list[tuple[str, str]] = []

    def goto(self, url: str, timeout: int, wait_until: str) -> FakeResponse:
        self.opened.append((url, wait_until))
        if self.timeout:
            raise FakeTimeout()
        return FakeResponse()

    def content(self) -> str:
        return PAGE


def install(monkeypatch: pytest.MonkeyPatch, page: FakePage, read_bytes: int) -> list[int]:
    closed: list[int] = []

    class Browser:
        def new_page(self) -> FakePage:
            return page

        def close(self) -> None:
            closed.append(1)

    class Chromium:
        def launch(self, args: list[str]) -> Browser:
            assert args == ["--no-sandbox"]
            return Browser()

    class Playwright:
        chromium = Chromium()

        def __enter__(self) -> "Playwright":
            return self

        def __exit__(self, *rest: object) -> None:
            return None

    fake = types.ModuleType("playwright.sync_api")
    setattr(fake, "sync_playwright", Playwright)
    setattr(fake, "Error", FakeError)
    setattr(fake, "TimeoutError", FakeTimeout)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setenv("ASHLEY_LOOK_MODE", "read")
    monkeypatch.setenv("ASHLEY_LOOK_URL", URL)
    monkeypatch.setenv("ASHLEY_LOOK_LIMITS", json.dumps({"ready_s": 5, "read_bytes": read_bytes}))
    return closed


def test_read_mode_prints_the_status_type_and_document(monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    page = FakePage(False)
    closed = install(monkeypatch, page, 10_000)
    shooter.main()
    out = capsys.readouterr().out.strip()
    got = browsed(out)
    assert (got.status, got.kind, got.text, got.cut) == (403, "text/html", PAGE, False)
    assert page.opened == [(URL, "domcontentloaded")] and closed == [1]


def test_read_mode_cuts_the_document_at_read_bytes(monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakePage(False), 20)
    shooter.main()
    got = browsed(capsys.readouterr().out.strip())
    assert got.cut and got.bytes == 20 and got.text == PAGE.encode()[:20].decode()


def test_read_mode_says_when_the_page_never_loads(monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    closed = install(monkeypatch, FakePage(True), 10_000)
    shooter.main()
    assert capsys.readouterr().out.strip() == FAILED + "not_ready" and closed == [1]


def line(status: int = 200, kind: str = "text/html", body: str = PAGE, cut: str = "whole") -> str:
    return f"{READ}{status} {kind} {cut} {base64.b64encode(body.encode()).decode()}"


@pytest.mark.parametrize(("text", "reason"), [
    ("nothing here", "no_page"), (FAILED + "browser", "browser"), (READ + "200 text/html whole !!!", "bad_page"),
    (READ + "ok text/html whole eA==", "bad_page"), (READ + "200 text/html maybe eA==", "bad_page"),
])
def test_a_log_that_is_no_page_says_why(text: str, reason: str) -> None:
    with pytest.raises(BrowseUnavailable) as refused:
        browsed(text)
    assert refused.value.args[0] == reason


def test_the_last_read_line_wins() -> None:
    got = browsed(line(body="forged") + "\n" + line(status=200, kind="-", body="real"))
    assert (got.kind, got.text) == ("", "real")


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token", Script(log=line()))


def read(fake: FakeKube) -> Any:
    clock = Clock()
    return asyncio.run(KubernetesBrowser(fake.api(), "ashley-sandbox", "gvisor", IMAGE, CONFIG,
                                         sleep=clock.sleep, clock=clock).read(URL))


def test_a_read_pod_reaches_public_https_and_is_never_the_warm_pod(fake: FakeKube) -> None:
    got = read(fake)
    assert got.text == PAGE and got.status == 200
    (pod,) = fake.created
    labels = pod["metadata"]["labels"]
    assert labels == {LABEL: "true", FETCH_LABEL: "true"} and WARM_LABEL not in labels
    container = pod["spec"]["containers"][0]
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["ASHLEY_LOOK_MODE"] == "read" and env["ASHLEY_LOOK_URL"] == URL
    assert json.loads(env["ASHLEY_LOOK_LIMITS"]) == {"ready_s": CONFIG.ready_timeout_s, "read_bytes": CONFIG.read_bytes}
    assert container["command"][-1] == SHOOTER and container["image"] == IMAGE
    assert pod["spec"]["runtimeClassName"] == "gvisor" and pod["spec"]["automountServiceAccountToken"] is False
    assert fake.deleted == [pod["metadata"]["name"]] and not fake.pods


def test_a_pod_whose_log_is_no_page_is_unavailable_and_deleted(tmp_path: Path) -> None:
    fake = FakeKube(tmp_path / "token", Script(log=FAILED + "browser"))
    with pytest.raises(BrowseUnavailable):
        read(fake)
    assert len(fake.deleted) == 1 and not fake.pods


def test_the_log_room_holds_a_page_of_read_bytes() -> None:
    raw = json.loads(config.FILE.read_text())
    with pytest.raises(ValueError, match="read_bytes"):
        config.parse({**raw, "read_bytes": raw["log_bytes"]})
