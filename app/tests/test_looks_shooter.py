"""`shooter.py`, the program a look pod runs, against a fake Playwright: it waits for the page to say it is drawn, steps
the JPEG quality down until the picture fits, and says why when it cannot."""

import base64
import json
import sys
import types
from typing import Any

import pytest
from ashley.looks import shooter

LIMITS = {"width": 1280, "height": 800, "max_height": 2400, "quality": 80, "max_bytes": 100, "ready_s": 5}


class FakeError(Exception):
    pass


class FakeTimeout(FakeError):
    pass


class FakePage:
    def __init__(self, sizes: list[int], timeout: bool, tall: int) -> None:
        self.sizes, self.timeout, self.tall = sizes, timeout, tall
        self.shots: list[dict[str, Any]] = []
        self.opened: list[str] = []
        self.closed = 0

    def goto(self, url: str, timeout: int) -> None:
        self.opened.append(url)

    def wait_for_selector(self, selector: str, timeout: int) -> None:
        assert selector == 'body[data-look="ready"]'
        if self.timeout:
            raise FakeTimeout()

    def evaluate(self, script: str) -> int:
        return self.tall

    def screenshot(self, **kwargs: Any) -> bytes:
        self.shots.append(kwargs)
        return b"\xff\xd8\xff" + b"x" * (self.sizes[min(len(self.shots), len(self.sizes)) - 1] - 3)


def install(monkeypatch: pytest.MonkeyPatch, page: FakePage, launch_error: bool = False) -> None:
    class Browser:
        def new_page(self, viewport: dict[str, int]) -> FakePage:
            assert viewport == {"width": 1280, "height": 800}
            return page

        def close(self) -> None:
            page.closed += 1

    class Chromium:
        def launch(self, args: list[str]) -> Browser:
            if launch_error:
                raise FakeError()
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
    monkeypatch.setenv("ASHLEY_LOOK_URL", "http://app/look/secret-token")
    monkeypatch.setenv("ASHLEY_LOOK_LIMITS", json.dumps(LIMITS))


def run(capsys: pytest.CaptureFixture[str]) -> str:
    shooter.main()
    return capsys.readouterr().out.strip()


def test_a_picture_that_fits_is_printed_as_base64_after_the_mark(monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    page = FakePage([50], False, 500)
    install(monkeypatch, page)
    out = run(capsys)
    assert out.startswith(shooter.MARK)
    assert base64.b64decode(out[len(shooter.MARK):]).startswith(b"\xff\xd8\xff")
    assert page.shots == [{"type": "jpeg", "quality": 80, "full_page": True,
                           "clip": {"x": 0, "y": 0, "width": 1280, "height": 800}}]
    assert "secret-token" not in out


def test_a_tall_page_is_cut_at_max_height_and_a_short_one_fills_the_viewport(monkeypatch: pytest.MonkeyPatch,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    page = FakePage([50], False, 9000)
    install(monkeypatch, page)
    run(capsys)
    assert page.shots[0]["clip"]["height"] == 2400


def test_quality_steps_down_until_the_picture_fits(monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    page = FakePage([500, 300, 80], False, 800)
    install(monkeypatch, page)
    assert run(capsys).startswith(shooter.MARK)
    assert [s["quality"] for s in page.shots] == [80, 60, 40]


def test_a_picture_that_never_fits_says_too_large(monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakePage([500], False, 800))
    assert run(capsys) == shooter.FAILED + "too_large"


def test_a_page_that_is_never_ready_says_so(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakePage([50], True, 800))
    assert run(capsys) == shooter.FAILED + "not_ready"


def test_a_browser_that_will_not_start_says_so(monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakePage([50], False, 800), launch_error=True)
    assert run(capsys) == shooter.FAILED + "browser"


def test_the_browser_is_closed_after_a_look_however_it_ends(monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    drawn, unready = FakePage([50], False, 800), FakePage([50], True, 800)
    for page in (drawn, unready):
        install(monkeypatch, page)
        run(capsys)
        assert page.closed == 1


PREFIX = "http://ashley.ashley.svc:8080/look/"


@pytest.mark.parametrize(("url", "expected"), [
    (PREFIX + "tok", PREFIX + "tok"),
    (PREFIX + "tok?a=../b", PREFIX + "tok?a=../b"),
    (PREFIX + "a/./b/../c", PREFIX + "a/c"),
    (PREFIX + "a/%2E%2e/b", PREFIX + "b"),
    (PREFIX + "a\\b", PREFIX + "a/b"),
    (PREFIX + "a/.\t./b", PREFIX + "b"),
    (PREFIX + "tok/..", PREFIX),
    (PREFIX + "tok/%2e", PREFIX + "tok/"),
    ("HTTP://ASHLEY.ashley.svc:8080/look/tok", PREFIX + "tok"),
    (PREFIX + "tok%2F..%2Fx", PREFIX + "tok%2F..%2Fx"),
    (PREFIX + "../look/tok", PREFIX + "tok"),
    (PREFIX + "../../look/tok", PREFIX + "tok"),
    (PREFIX + "..", None),
    ("http://ashley.ashley.svc:8080/look/tok/../../../api", None),
    ("http://ashley.ashley.svc:8080\\@evil.example/look/tok", None),
])
def test_the_address_handed_to_the_browser_is_the_one_the_browser_resolves(url: str, expected: str | None) -> None:
    assert shooter.resolved(url, PREFIX) == expected
