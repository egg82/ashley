"""The program a browser session's pod runs (`python -I -B -c <this file's text>`): one headless Chromium, one page, driven
over HTTP on `PORT` by the app for the minutes the session lasts. `POST /snapshot` answers with the page's accessibility
tree, each interactive element named by a reference (`e0`, `e1`, ...); `POST /act` does one `navigate` (to an https
address), `click`, `type` (with `submit` to press Enter) or `select` on a reference. Every request carries the session's
bearer token (`ASHLEY_LOOK_TOKEN`); `GET /healthz` answers without it once the page is up.

An action on a reference never trusts it: the page is snapshotted again, and the element must be there under the same
role and name (and the same place among those that share them) as in the snapshot the reference was given in, or the
action is refused as `stale_ref`. Nothing is aimed by screen position. A field for a password, a one-time code or a card
(`secret` in the snapshot) refuses `type` as `secret_field`: those are not for her to type.

The session is bounded by the limits in `ASHLEY_LOOK_LIMITS` (JSON: `width`, `height`, `session_max_s`,
`session_max_actions`, `session_step_s`, `snapshot_nodes`, `snapshot_name_chars`): past `session_max_s`, or an action
past `session_max_actions`, a request is answered `410` with `ended` (`time` or `actions`) and the program exits. It
prints only counts, never an address or anything the page held."""

import hmac
import importlib
import json
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

PORT = 8080
MAX_BODY = 4096
REF = re.compile(r"e(\d+)")
SNAPSHOT_JS = """(limits) => {
  document.querySelectorAll('[data-ashley-ref]').forEach((el) => el.removeAttribute('data-ashley-ref'));
  const kinds = {checkbox: 'checkbox', radio: 'radio', button: 'button', submit: 'button', reset: 'button',
                 image: 'button', range: 'slider', search: 'searchbox'};
  const roles = {a: 'link', button: 'button', select: 'combobox', textarea: 'textbox', summary: 'button'};
  const text = (s) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, limits.name);
  const labelled = (el) => {
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
    return ids.map((id) => (document.getElementById(id) || {}).innerText || '').join(' ');
  };
  const nameOf = (el) => text(el.getAttribute('aria-label') || labelled(el)
    || (el.labels && el.labels[0] ? el.labels[0].innerText : '') || el.getAttribute('alt')
    || (el.tagName === 'INPUT' && kinds[el.type] === 'button' ? el.value : '')
    || el.innerText || el.placeholder || el.title);
  const secret = (el) => el.tagName === 'INPUT' && (el.type === 'password'
    || /^(cc-|one-time-code|current-password|new-password)/.test(el.autocomplete || ''));
  const found = [];
  let cut = false;
  const query = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role],[contenteditable],h1,h2,h3,h4,h5,h6';
  for (const el of document.querySelectorAll(query)) {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || (box.width === 0 && box.height === 0)) continue;
    if (found.length >= limits.nodes) { cut = true; break; }
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || (tag === 'input' ? kinds[el.type] || 'textbox'
      : /^h[1-6]$/.test(tag) ? 'heading' : el.isContentEditable ? 'textbox' : roles[tag] || 'generic');
    el.setAttribute('data-ashley-ref', String(found.length));
    const node = {role: role, name: nameOf(el)};
    if (secret(el)) node.secret = true;
    if (el.disabled) node.disabled = true;
    if (el.checked) node.checked = true;
    if (tag === 'select') node.options = Array.from(el.options).slice(0, 30).map((o) => text(o.label));
    found.push(node);
  }
  return {nodes: found, cut: cut};
}"""

Key = tuple[str, str, int]


class Refused(Exception):
    """The request cannot be done; `args[0]` is the reason the app is told."""


def keyed(nodes: list[dict[str, Any]]) -> list[Key]:
    """Each node's identity: its role, its name, and its place (from 0) among the nodes sharing both."""
    seen: Counter[tuple[str, str]] = Counter()
    keys: list[Key] = []
    for node in nodes:
        pair = (str(node["role"]), str(node["name"]))
        keys.append((*pair, seen[pair]))
        seen[pair] += 1
    return keys


class Session:
    def __init__(self, api: Any, page: Any, limits: dict[str, int], clock: Callable[[], float] = time.monotonic) -> None:
        self._api = api
        self._page = page
        self._limits = limits
        self._clock = clock
        self._started = clock()
        self._actions = 0
        self._seen: list[Key] = []

    def handle(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """`(status, answer)` for a request: 200, 400 with the `reason` it was refused, or 410 with how it `ended`."""
        over = self.over(path == "/act")
        if over is not None:
            return 410, {"ended": over}
        try:
            return 200, (self._act(body) if path == "/act" else self._snapshot())
        except Refused as e:
            return 400, {"reason": str(e)}
        except self._api.TimeoutError:
            return 400, {"reason": "page_timeout"}
        except self._api.Error:
            return 400, {"reason": "page_error"}

    def over(self, acting: bool) -> str | None:
        """How the session has ended: `time` for any request, `actions` for one that would act."""
        if self._clock() - self._started >= self._limits["session_max_s"]:
            return "time"
        if acting and self._actions >= self._limits["session_max_actions"]:
            return "actions"
        return None

    def counts(self) -> dict[str, int]:
        left = self._limits["session_max_s"] - (self._clock() - self._started)
        return {"seconds_left": max(0, int(left)), "actions_left": self._limits["session_max_actions"] - self._actions}

    def _nodes(self) -> tuple[list[dict[str, Any]], bool]:
        got = self._page.evaluate(SNAPSHOT_JS, {"nodes": self._limits["snapshot_nodes"],
                                                "name": self._limits["snapshot_name_chars"]})
        return list(got["nodes"]), bool(got["cut"])

    def _snapshot(self) -> dict[str, Any]:
        nodes, cut = self._nodes()
        self._seen = keyed(nodes)
        shown = [{"ref": f"e{i}", **node} for i, node in enumerate(nodes)]
        return {"url": self._page.url, "title": self._page.title(), "nodes": shown, "cut": cut, **self.counts()}

    def _target(self, ref: object) -> tuple[int, dict[str, Any]]:
        """The element `ref` was given for, found again in a fresh snapshot, as its index there and node."""
        found = REF.fullmatch(ref) if isinstance(ref, str) else None
        if found is None:
            raise Refused("bad_request")
        if int(found.group(1)) >= len(self._seen):
            raise Refused("no_such_ref")
        nodes, _ = self._nodes()
        try:
            index = keyed(nodes).index(self._seen[int(found.group(1))])
        except ValueError:
            raise Refused("stale_ref") from None
        return index, nodes[index]

    def _act(self, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action")
        step_ms = self._limits["session_step_s"] * 1000
        if action == "navigate":
            url = body.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise Refused("bad_request")
            self._actions += 1
            self._page.goto(url, timeout=step_ms, wait_until="domcontentloaded")
            return self.counts()
        if action not in ("click", "type", "select"):
            raise Refused("bad_request")
        index, node = self._target(body.get("ref"))
        field = body.get("text") if action == "type" else body.get("value")
        if action != "click" and not isinstance(field, str):
            raise Refused("bad_request")
        if action == "type" and node.get("secret"):
            raise Refused("secret_field")
        self._actions += 1
        element = self._page.locator(f'[data-ashley-ref="{index}"]')
        if action == "click":
            element.click(timeout=step_ms)
        elif action == "type":
            element.fill(field, timeout=step_ms)
            if body.get("submit") is True:
                element.press("Enter", timeout=step_ms)
        else:
            element.select_option(label=field, timeout=step_ms)
        return self.counts()


def handler(session: Session, token: str, on_end: Callable[[], None]) -> type[BaseHTTPRequestHandler]:
    """The HTTP side: `token` as a bearer token on every request but `/healthz`; `on_end` runs once a request was
    answered `410`."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(200 if self.path == "/healthz" else 404, {})

        def do_POST(self) -> None:
            if self.path not in ("/snapshot", "/act"):
                self._send(404, {})
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self._send(401, {})
                return
            length = int(self.headers.get("Content-Length") or 0)
            loaded: object = {}
            try:
                loaded = json.loads(self.rfile.read(length)) if 0 < length <= MAX_BODY else {}
            except ValueError:
                pass
            loose: Any = loaded
            body: dict[str, Any] = {}
            if isinstance(loaded, dict):
                body = {str(k): v for k, v in dict[Any, Any](loose).items()}
            status, answer = session.handle(self.path, body)
            self._send(status, answer)
            if status == 410:
                on_end()

        def _send(self, status: int, answer: dict[str, Any]) -> None:
            data = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Handler


def main() -> None:
    api: Any = importlib.import_module("playwright.sync_api")
    limits: dict[str, int] = json.loads(os.environ["ASHLEY_LOOK_LIMITS"])
    with api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            context = browser.new_context(viewport={"width": limits["width"], "height": limits["height"]},
                                          accept_downloads=False)
            session = Session(api, context.new_page(), limits)
            server = HTTPServer(("", PORT), handler(session, os.environ["ASHLEY_LOOK_TOKEN"],
                                                    lambda: threading.Thread(target=server.shutdown).start()))
            server.serve_forever()
            print("looks.session_ended actions=" + str(limits["session_max_actions"] - session.counts()["actions_left"]),
                  flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
