"""The one logging setup, for every entry point: one logfmt line per event to stdout, which Alloy ships to Loki.

    ts=2026-10-24T09:00:01.123Z level=info logger=ashley.api event=http.request method=GET route=/api/ready status=200 ms=4

Call sites say `logs.info(log, "migrate.done", ms=16)`; a field is an id, a count, a kind, a duration or a status.
Never written: people's data, conversation content, prompts, keys, tokens, cookies, emails, client addresses, query
strings. An exception is written as its type chain and its frames (file:line:function); its message is never written,
because a database or parser error can echo a row. A library's own lines are dropped, the server's lifecycle lines
aside: they carry hosts and URLs."""

import logging
import os
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType

_MAX = 300
_SILENT = ("uvicorn.access", "psycopg", "psycopg.pool", "httpx", "httpx2", "httpcore", "asyncio", "alembic", "hikari")
_PACKAGE = "ashley/"
_SERVER = "uvicorn.error"   # its lines are the server's own lifecycle (start, stop); the client's are never in them


def _val(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        v = round(v, 2)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    if len(s) > _MAX:
        s = s[:_MAX] + "..."
    return f'"{s}"' if not s or any(ch in s for ch in ' ="\\') else s


def _frames(tb: TracebackType | None) -> str:
    out: list[str] = []
    for f in traceback.extract_tb(tb)[-12:]:
        name = f.filename.replace("\\", "/")
        name = name.split(_PACKAGE, 1)[1] if _PACKAGE in name else name.rsplit("/", 1)[-1]
        out.append(f"{name}:{f.lineno}:{f.name}")
    return ">".join(out)


def _chain(exc: BaseException | None) -> str:
    seen: set[int] = set()
    types: list[str] = []
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        types.append(type(exc).__name__)
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return "<".join(types)


class Logfmt(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.")
        fields: Mapping[str, object] | None = getattr(record, "fields", None)
        parts: list[tuple[str, object]] = [
            ("ts", f"{ts}{int(record.msecs):03d}Z"),
            ("level", record.levelname.lower()),
            ("logger", record.name),
        ]
        if fields is None:
            parts += [("event", "log")]
            if record.name == _SERVER:
                parts.append(("msg", record.getMessage()))
        else:
            parts.append(("event", record.msg))
            parts += [(k, v) for k, v in fields.items() if v is not None]
        if record.exc_info and record.exc_info[1] is not None:
            parts += [("exc", _chain(record.exc_info[1])), ("tb", _frames(record.exc_info[2]))]
        return " ".join(f"{k}={_val(v)}" for k, v in parts)


class _Stdout(logging.Handler):
    """Writes to stdout as it is when a line is written, not when the handler was made (a test swaps it)."""

    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout.write(self.format(record) + "\n")
        sys.stdout.flush()


def setup(env: Mapping[str, str] = os.environ) -> None:
    """Idempotent. Level from LOG_LEVEL (default info)."""
    level = logging.getLevelNamesMapping().get((env.get("LOG_LEVEL") or "info").strip().upper(), logging.INFO)
    root = logging.getLogger()
    if not any(isinstance(h, _Stdout) for h in root.handlers):
        handler = _Stdout()
        handler.setFormatter(Logfmt())
        root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", _SERVER):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    for name in _SILENT:
        logging.getLogger(name).disabled = True


def _emit(log: logging.Logger, level: int, event: str, exc: bool, fields: dict[str, object]) -> None:
    if log.isEnabledFor(level):
        log.log(level, event, extra={"fields": fields}, exc_info=exc)


def info(log: logging.Logger, event: str, **fields: object) -> None:
    _emit(log, logging.INFO, event, False, fields)


def warning(log: logging.Logger, event: str, **fields: object) -> None:
    _emit(log, logging.WARNING, event, False, fields)


def error(log: logging.Logger, event: str, exc: bool = False, **fields: object) -> None:
    """`exc=True` inside an `except` block adds the exception's type chain and frames."""
    _emit(log, logging.ERROR, event, exc, fields)
