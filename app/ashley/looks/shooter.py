"""The program a look pod runs (`python -I -B -c <this file's text>`): open the page named by `ASHLEY_LOOK_URL` in
headless Chromium through Playwright, wait for the page to say it is drawn (`body[data-look="ready"]`), and print one
line, `MARK` then base64 of a JPEG of the page, or `FAILED` then a short reason. The size limits come in
`ASHLEY_LOOK_LIMITS` as JSON: `width`, `height`, `max_height`, `quality`, `max_bytes` and `ready_s`. Quality steps down
until the picture fits `max_bytes`. Never prints the URL, which is a credential, nor anything the page held.

With `ASHLEY_LOOK_MODE=serve` it is the warm pod instead (`serve`): it stays up and takes one look at a time over HTTP,
`POST /look` with `{"url": ...}` (only under `ASHLEY_LOOK_PREFIX`), answering with the same line; `503` when a look is
running, `GET /healthz` when it is ready. Each look launches its own browser and closes it, and removes the files the
look left in `TMPDIR`, so nothing one look held reaches the next.

With `ASHLEY_LOOK_MODE=read` it reads a public page instead (`read`): open `ASHLEY_LOOK_URL`, wait for its document to
load, and print one line, `READ`, the main response's status, its content type (`-` when none) and base64 of the
document as the browser holds it, cut to `read_bytes` (from the limits) as UTF-8; or `FAILED` and why. The browser is
Chromium as it comes; nothing about it is disguised."""

import base64
import importlib
import json
import os
import queue
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MARK = "ashley-look "
READ = "ashley-read "
FAILED = "ashley-look-failed "
STEPS = (1.0, 0.75, 0.5)
PORT = 8080
MAX_BODY = 4096
DROPPED = str.maketrans("", "", "\t\n\r")
DOT_SEGMENTS = {".": ".", "%2e": ".", "..": "..", ".%2e": "..", "%2e.": "..", "%2e%2e": ".."}


def qualities(quality: int) -> list[int]:
    """`quality` and then lower, each a fraction of it, never under 1."""
    return [max(1, int(quality * step)) for step in STEPS]


def drawn(browser: Any, url: str, limits: dict[str, int]) -> str:
    page = browser.new_page(viewport={"width": limits["width"], "height": limits["height"]})
    page.goto(url, timeout=limits["ready_s"] * 1000)
    page.wait_for_selector('body[data-look="ready"]', timeout=limits["ready_s"] * 1000)
    tall = min(int(page.evaluate("document.documentElement.scrollHeight")), limits["max_height"])
    clip = {"x": 0, "y": 0, "width": limits["width"], "height": max(tall, limits["height"])}
    for quality in qualities(limits["quality"]):
        data = page.screenshot(type="jpeg", quality=quality, full_page=True, clip=clip)
        if len(data) <= limits["max_bytes"]:
            return MARK + base64.b64encode(data).decode("ascii")
    return FAILED + "too_large"


def shoot(api: Any, p: Any, url: str, limits: dict[str, int]) -> str:
    """The line to print for the page at `url`: `MARK` and the picture, or `FAILED` and why."""
    try:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            return drawn(browser, url, limits)
        finally:
            browser.close()
    except api.TimeoutError:
        return FAILED + "not_ready"
    except api.Error:
        return FAILED + "browser"


def document(browser: Any, url: str, limits: dict[str, int]) -> str:
    page = browser.new_page()
    response = page.goto(url, timeout=limits["ready_s"] * 1000, wait_until="domcontentloaded")
    status = 0 if response is None else int(response.status)
    kind = "" if response is None else str(response.headers.get("content-type", "")).split(";")[0].strip().lower()
    body = page.content().encode("utf-8")
    cut = "cut" if len(body) > limits["read_bytes"] else "whole"
    data = base64.b64encode(body[:limits["read_bytes"]]).decode("ascii")
    return f"{READ}{status} {kind or '-'} {cut} {data}"


def read(api: Any, p: Any, url: str, limits: dict[str, int]) -> str:
    """The line to print for the public page at `url`: `READ` and what the browser was given, or `FAILED` and why."""
    try:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            return document(browser, url, limits)
        finally:
            browser.close()
    except api.TimeoutError:
        return FAILED + "not_ready"
    except api.Error:
        return FAILED + "browser"


def main() -> None:
    api: Any = importlib.import_module("playwright.sync_api")
    limits: dict[str, int] = json.loads(os.environ["ASHLEY_LOOK_LIMITS"])
    take = read if os.environ.get("ASHLEY_LOOK_MODE") == "read" else shoot
    with api.sync_playwright() as p:
        print(take(api, p, os.environ["ASHLEY_LOOK_URL"], limits), flush=True)


Job = tuple[str, "queue.Queue[str]"]


def dot_free(path: str) -> str:
    """`path` with its `.` and `..` segments removed the way a browser does (RFC 3986 section 5.2.4), a segment
    counting as a dot segment however its dots are percent-encoded."""
    out: list[str] = []
    parts = path.split("/")
    for i, part in enumerate(parts):
        dots = DOT_SEGMENTS.get(part.lower())
        if dots is None:
            out.append(part)
            continue
        if dots == ".." and len(out) > 1:
            out.pop()
        if i == len(parts) - 1:
            out.append("")
    return "/".join(out)


def resolved(url: str, prefix: str) -> str | None:
    """The address a browser would navigate to for `url` (tabs and newlines dropped, `\\` read as `/` before the query
    or fragment, dot segments removed), or None when that is not under `prefix`: same scheme, host and port, and a path
    that starts with the prefix's path."""
    text = url.translate(DROPPED).strip()
    end = next((i for i, c in enumerate(text) if c in "?#"), len(text))
    parts = urlsplit(text[:end].replace("\\", "/") + text[end:])
    base = urlsplit(prefix)
    path = dot_free(parts.path)
    if (parts.scheme.lower(), parts.netloc.lower()) != (base.scheme, base.netloc.lower()) or not path.startswith(base.path):
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, parts.fragment))


def handler(prefix: str, jobs: "queue.Queue[Job]", gate: threading.Lock, wait_s: float) -> type[BaseHTTPRequestHandler]:
    """The HTTP side of the warm pod: `gate` admits one look at a time (a second gets 503, to be taken elsewhere),
    `jobs` hands it to the thread that owns Playwright."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(200 if self.path == "/healthz" else 404, "")

        def do_POST(self) -> None:
            url = self._url()
            if url is None:
                return
            if not gate.acquire(blocking=False):
                self._send(503, "")
                return
            answer: str | None = None
            try:
                reply: "queue.Queue[str]" = queue.Queue()
                jobs.put((url, reply))
                answer = reply.get(timeout=wait_s)
            except queue.Empty:
                pass
            finally:
                gate.release()
            if answer is None:
                self._send(504, "")
            else:
                self._send(200, answer)

        def _url(self) -> str | None:
            """The page to draw, or None after answering why not."""
            length = int(self.headers.get("Content-Length") or 0)
            if self.path != "/look" or not 0 < length <= MAX_BODY:
                self._send(404 if self.path != "/look" else 400, "")
                return None
            try:
                url = json.loads(self.rfile.read(length))["url"]
            except (ValueError, KeyError, TypeError):
                url = None
            address = resolved(url, prefix) if isinstance(url, str) else None
            if address is None:
                self._send(400, "")
                return None
            return address

        def _send(self, status: int, text: str) -> None:
            body = text.encode("ascii")
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Handler


def clear(tmp: str, before: set[str]) -> None:
    """Remove what appeared in `tmp` since `before` was listed."""
    for name in set(os.listdir(tmp)) - before:
        path = os.path.join(tmp, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


def serve_one(jobs: "queue.Queue[Job]", api: Any, p: Any, limits: dict[str, int], tmp: str) -> None:
    """Take the next look: a browser of its own, closed after, and what it left in `tmp` removed."""
    url, reply = jobs.get()
    before = set(os.listdir(tmp))
    try:
        line = shoot(api, p, url, limits)
    except Exception as e:
        print("looks.warm_error type=" + type(e).__name__, flush=True)
        line = FAILED + "browser"
    clear(tmp, before)
    reply.put(line)


def serve() -> None:
    api: Any = importlib.import_module("playwright.sync_api")
    limits: dict[str, int] = json.loads(os.environ["ASHLEY_LOOK_LIMITS"])
    wait_s = float(os.environ["ASHLEY_LOOK_WAIT_S"])
    tmp = os.environ["TMPDIR"]
    jobs: "queue.Queue[Job]" = queue.Queue()
    server = ThreadingHTTPServer(("", PORT), handler(os.environ["ASHLEY_LOOK_PREFIX"], jobs, threading.Lock(), wait_s))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with api.sync_playwright() as p:
        while True:
            serve_one(jobs, api, p, limits, tmp)


if __name__ == "__main__":
    if os.environ.get("ASHLEY_LOOK_MODE") == "serve":
        serve()
    else:
        main()
