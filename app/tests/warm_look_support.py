"""Doubles for the warm look pod's suites: a Playwright that records every browser it launches and closes."""

import json
import sys
import types
from typing import Any

import pytest
from ashley.looks.shooter import FAILED

LIMITS = {"width": 1280, "height": 800, "max_height": 2400, "quality": 80, "max_bytes": 100, "ready_s": 5}


class Launched:
    """What the fake Playwright was asked: one entry per browser, in order."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[int] = []
        self.launches = 0


class Page:
    def __init__(self, launched: Launched, number: int, tmp: str, fail: bool) -> None:
        self.launched, self.number, self.tmp, self.fail = launched, number, tmp, fail

    def goto(self, url: str, timeout: int) -> None:
        self.launched.opened.append(url)
        with open(f"{self.tmp}/profile-{self.number}", "w") as f:
            f.write("browser state")

    def wait_for_selector(self, selector: str, timeout: int) -> None:
        return None

    def evaluate(self, script: str) -> int:
        if self.fail:
            raise RuntimeError("boom")
        return 800

    def screenshot(self, **kwargs: Any) -> bytes:
        return b"\xff\xd8\xff" + b"x" * 20


class Browser:
    def __init__(self, launched: Launched, number: int, tmp: str, fail: bool) -> None:
        self.launched, self.number, self.tmp, self.fail = launched, number, tmp, fail

    def new_page(self, viewport: dict[str, int]) -> Page:
        return Page(self.launched, self.number, self.tmp, self.fail)

    def close(self) -> None:
        self.launched.closed.append(self.number)


def playwright(monkeypatch: pytest.MonkeyPatch, tmp: str, fail_on: int = 0) -> tuple[Any, Any, Launched]:
    """The `api` and `p` the shooter takes, launching browsers that write into `tmp`; launch number `fail_on` (1-based)
    raises from the page."""
    launched = Launched()

    class Error(Exception):
        pass

    class Chromium:
        def launch(self, args: list[str]) -> Browser:
            launched.launches += 1
            return Browser(launched, launched.launches, tmp, launched.launches == fail_on)

    api = types.SimpleNamespace(Error=Error, TimeoutError=type("T", (Error,), {}))
    p = types.SimpleNamespace(chromium=Chromium())
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    return api, p, launched


def line_is_picture(line: str) -> bool:
    return line.startswith("ashley-look ") and not line.startswith(FAILED)


def body(url: str) -> bytes:
    return json.dumps({"url": url}).encode()


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    """The fields of each logged `event`, in order."""
    return [getattr(r, "fields", {}) for r in caplog.records if r.getMessage() == event]
