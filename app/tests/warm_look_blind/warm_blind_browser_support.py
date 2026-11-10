"""A pretend Playwright (its public sync API: `Error`, `TimeoutError`, `chromium.launch`, pages) whose browsers record
what happened to them, for the warm look pod's blind tests."""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


class PwError(Exception):
    pass


class PwTimeout(PwError):
    pass


@dataclass
class Script:
    """What the pretend browsers do. `ready` False makes every wait for the page time out; `sizes` is how many bytes a
    JPEG is at each quality (default: 20 per quality point); `goto_error` fails the navigation; `launch_error` fails the
    launch; `leave` is what a launch writes into `tmp` (relative paths, a name ending in `/` is a directory)."""

    ready: bool = True
    scale: int = 20
    goto_error: Exception | None = None
    launch_error: Exception | None = None
    leave: tuple[str, ...] = ()
    height: int = 1000
    delay_s: float = 0.0
    seen_tmp: list[list[str]] = field(default_factory=list[list[str]])
    events: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    gotos: list[str] = field(default_factory=list[str])
    waits: list[tuple[str, object]] = field(default_factory=list[tuple[str, object]])
    qualities: list[object] = field(default_factory=list[object])
    clips: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    launches: int = 0


class FakePage:
    def __init__(self, script: Script, ident: int) -> None:
        self.script = script
        self.ident = ident
        self.url = "about:blank"

    def _tell(self, name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.script.waits.append((name, kwargs.get("timeout")))
            return None

        return call

    def goto(self, url: str, **kwargs: Any) -> None:
        self.script.gotos.append(url)
        if self.script.goto_error is not None:
            raise self.script.goto_error
        self.url = url

    def wait_ready(self, name: str, kwargs: dict[str, Any]) -> None:
        self.script.waits.append((name, kwargs.get("timeout")))
        if not self.script.ready:
            raise PwTimeout("Timeout exceeded")

    def wait_for_selector(self, selector: str, **kwargs: Any) -> "FakePage":
        self.wait_ready("selector", kwargs)
        return self

    def wait_for_function(self, expression: str, *args: Any, **kwargs: Any) -> None:
        self.wait_ready("function", kwargs)

    def locator(self, selector: str, **kwargs: Any) -> "FakeLocator":
        return FakeLocator(self)

    def query_selector(self, selector: str) -> "FakePage | None":
        return self if self.script.ready else None

    def evaluate(self, expression: str, *args: Any) -> int:
        return self.script.height

    def screenshot(self, **kwargs: Any) -> bytes:
        quality = kwargs.get("quality")
        time.sleep(self.script.delay_s)
        self.script.qualities.append(quality)
        clip: Any = kwargs.get("clip")
        if clip:
            self.script.clips.append(dict(clip))
        size = (int(quality) if isinstance(quality, int | float) else 100) * self.script.scale
        return (bytes.fromhex("ffd8ff") + b"j" * size)[:size] if size > 3 else bytes.fromhex("ffd8ff")

    def set_viewport_size(self, *args: Any, **kwargs: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., Any]:
        return self._tell(name)


class FakeLocator:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def wait_for(self, **kwargs: Any) -> None:
        self.page.wait_ready("locator", kwargs)

    def count(self) -> int:
        return 1 if self.page.script.ready else 0


class FakeContext:
    def __init__(self, browser: "FakeBrowser") -> None:
        self.browser = browser

    def new_page(self, **kwargs: Any) -> FakePage:
        return self.browser.new_page()

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., Any]:
        return lambda *a, **k: None


class FakeBrowser:
    def __init__(self, script: Script, ident: int) -> None:
        self.script = script
        self.ident = ident
        self.closed = False

    def new_page(self, **kwargs: Any) -> FakePage:
        return FakePage(self.script, self.ident)

    def new_context(self, **kwargs: Any) -> FakeContext:
        return FakeContext(self)

    def close(self) -> None:
        self.closed = True
        self.script.events.append(("close", self.ident))

    def __getattr__(self, name: str) -> Callable[..., Any]:
        return lambda *a, **k: None


class FakeChromium:
    def __init__(self, script: Script, tmp: Path | None) -> None:
        self.script = script
        self.tmp = tmp

    def launch(self, **kwargs: Any) -> FakeBrowser:
        script = self.script
        if script.launch_error is not None:
            raise script.launch_error
        script.launches += 1
        ident = script.launches
        script.events.append(("launch", ident))
        if self.tmp is not None:
            script.seen_tmp.append(sorted(os.listdir(self.tmp)))
            for rel in script.leave:
                target = self.tmp / f"{rel.rstrip('/')}-{ident}"
                if rel.endswith("/"):
                    (target / "profile").mkdir(parents=True)
                    (target / "profile" / "cookies").write_text("session")
                else:
                    target.write_text("left behind")
        return FakeBrowser(script, ident)


def playwright(script: Script, tmp: Path | None = None) -> tuple[Any, Any]:
    """`(api, p)` as `shooter.shoot` takes them: Playwright's sync module (its `Error` and `TimeoutError`) and the
    started driver."""
    api = SimpleNamespace(Error=PwError, TimeoutError=PwTimeout)
    return api, SimpleNamespace(chromium=FakeChromium(script, tmp))
