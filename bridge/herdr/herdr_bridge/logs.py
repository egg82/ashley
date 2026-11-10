"""One logfmt line per call, to stdout (journald). Fields are call names, hashed ids, status codes and counts; never
text, paths, labels, the token or the person id."""

import hashlib
import sys
from typing import Protocol


class Log(Protocol):
    def emit(self, line: str) -> None: ...


class StdoutLog:
    def emit(self, line: str) -> None:
        print(line, file=sys.stdout, flush=True)


def short(session_id: str) -> str:
    """The first 8 hex digits of a session id's sha256: enough to follow one session through the log."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:8]


def call_line(call: str, session: str | None, status: int, ms: int, size: int, error: str | None) -> str:
    fields = [("call", call), ("session", session or "-"), ("status", str(status)), ("ms", str(ms)), ("bytes", str(size))]
    if error is not None:
        fields.append(("error", error))
    return " ".join(f"{k}={v}" for k, v in fields)
