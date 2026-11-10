"""The HTTP API as a function from a request to a response, with no sockets: authentication, routing, body checks and
the call log line. `server.py` carries it over TLS."""

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import __version__
from .auth import Auth
from .errors import BridgeError
from .files import Files, Limits
from .herdr import Herdr
from .jsonget import obj, text
from .logs import Log, call_line, short
from .runner import HerdrMissing, HerdrTimeout
from .sessions import Sessions

SESSION = r"/v1/sessions/([0-9a-fA-F-]{36})"
MAX_PROMPT = 8000
# Standard JSON escapes a character to at most 12 bytes (an astral character is two \uXXXX surrogates); the rest is
# the `{"text": ""}` envelope and whitespace.
ESCAPED_BYTES_PER_CHAR = 12
ENVELOPE_SLACK = 256
MAX_BODY = MAX_PROMPT * ESCAPED_BYTES_PER_CHAR + ENVELOPE_SLACK
LINES = (1, 400)
DEFAULT_LINES = 120


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: Mapping[str, str]
    headers: Mapping[str, str]  # keys lowercased
    body: bytes


@dataclass(frozen=True)
class Response:
    """A JSON `body`, or `raw` bytes (a downloaded file) in its place."""

    status: int
    body: dict[str, object]
    raw: bytes | None = None


class Api:
    def __init__(self, auth: Auth, sessions: Sessions, herdr: Herdr, log: Log, limits: Limits = Limits()) -> None:
        self.auth = auth
        self.sessions = sessions
        self.files = Files(sessions, limits)
        self.limits = limits
        self.herdr = herdr
        self.log = log

    def handle(self, req: Request) -> Response:
        began = time.monotonic()
        call, session = "unknown", None
        try:
            person = self.auth.check(req.headers.get("authorization"), req.headers.get("x-ashley-person"))
            call, session, act = self.route(req, person)
            answer = act()
            made = answer.get("id") if isinstance(answer, dict) else None  # a started session is named by its answer
            session = session or (made if isinstance(made, str) else None)
            res = Response(200, answer) if isinstance(answer, dict) else Response(200, {}, answer)
            error = None
        except BridgeError as e:
            res, error = Response(e.status, {"error": e.code}), e.code
        size = logged_size(call, res)
        ms = round((time.monotonic() - began) * 1000)
        self.log.emit(call_line(call, session and short(session), res.status, ms, size, error))
        return res

    def route(self, req: Request, person: str) -> tuple[str, str | None, Callable[[], dict[str, object] | bytes]]:
        """(call name, session id if the call names one, the work), so a refusal inside the work is still logged
        under its call."""
        key = (req.method, req.path)
        if key == ("GET", "/v1/whoami"):
            return "whoami", None, lambda: self.whoami(person)
        if key == ("GET", "/v1/sessions"):
            return "list", None, self.listing
        if key == ("POST", "/v1/sessions"):
            return "start", None, lambda: self.start(req)
        transfer = re.fullmatch(SESSION + r"/(in|out)(?:/(.*))?", req.path, re.DOTALL)
        if transfer is not None:
            return self.transfer(req, transfer[1].lower(), transfer[2], transfer[3])
        m = re.fullmatch(SESSION + r"/(read|prompt|close)", req.path)
        if m is None or req.method != ("GET" if m[2] == "read" else "POST"):
            raise BridgeError("not_found")
        sid, call = m[1].lower(), m[2]
        if call == "read":
            return call, sid, lambda: self.sessions.read(sid, lines(req.query.get("lines")))
        if call == "prompt":
            return call, sid, lambda: self.prompt(sid, req)
        return call, sid, lambda: self.close(sid)

    def transfer(self, req: Request, sid: str, direction: str,
                 name: str | None) -> tuple[str, str, Callable[[], dict[str, object] | bytes]]:
        if direction == "in" and name is not None and req.method == "PUT":
            return "upload", sid, lambda: self.files.upload(sid, name, self.upload_body(req))
        if direction == "out" and req.method == "GET":
            if name is None:
                return "outputs", sid, lambda: self.files.outputs(sid)
            return "download", sid, lambda: self.files.download(sid, name)
        raise BridgeError("not_found")

    def upload_body(self, req: Request) -> bytes:
        """The body of an upload, refused as `too_large` by its declared length or by what arrived, and as
        `bad_request` when it is chunked, undeclared or shorter than declared."""
        declared = req.headers.get("content-length", "")
        if "transfer-encoding" in req.headers or not declared.isascii() or not declared.isdigit():
            raise BridgeError("bad_request")
        if int(declared) > self.limits.max_file_bytes or len(req.body) > self.limits.max_file_bytes:
            raise BridgeError("too_large")
        if len(req.body) != int(declared):
            raise BridgeError("bad_request")
        return req.body

    def listing(self) -> dict[str, object]:
        return {"sessions": [s.wire() for s in self.sessions.sessions()], "last_typed_at": None,
                "roots": list(self.sessions.roots)}

    def prompt(self, sid: str, req: Request) -> dict[str, object]:
        self.sessions.prompt(sid, prompt_text(req.body))
        return {"submitted": True}

    def close(self, sid: str) -> dict[str, object]:
        self.sessions.close(sid)
        return {"closed": True}

    def whoami(self, person: str) -> dict[str, object]:
        try:
            version = self.herdr.version()
        except (HerdrMissing, HerdrTimeout):
            version = None
        return {"bridge_version": __version__, "herdr_version": version, "person": person, "capabilities": ["files"]}

    def start(self, req: Request) -> dict[str, object]:
        body = json_body(req.body)
        extra = set(body) - {"dir", "label", "model"}
        directory, label = text(body, "dir"), text(body, "label")
        model = body.get("model")
        if extra or directory is None or label is None or not (model is None or isinstance(model, str)):
            raise BridgeError("bad_request")
        return self.sessions.start(directory, label, model).wire()


def logged_size(call: str, res: Response) -> int:
    """The bytes a call moved: a file's own size for a transfer, else the size of the JSON answer."""
    if res.raw is not None:
        return len(res.raw)
    moved = res.body.get("bytes")
    return moved if call == "upload" and isinstance(moved, int) else len(json.dumps(res.body))


def lines(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_LINES
    if not raw.isascii() or not raw.isdigit() or not LINES[0] <= int(raw) <= LINES[1]:
        raise BridgeError("bad_request")
    return int(raw)


def json_body(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_BODY:
        raise BridgeError("bad_request")
    try:
        parsed: object = json.loads(raw)
    except ValueError as e:
        raise BridgeError("bad_request") from e
    is_object = isinstance(parsed, dict)
    if not is_object:
        raise BridgeError("bad_request")
    return obj(parsed)


def prompt_text(raw: bytes) -> str:
    body = json_body(raw)
    value = body.get("text")
    if set(body) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > MAX_PROMPT or "\x00" in value:
        raise BridgeError("bad_request")
    return value
