"""When a person last typed into a Claude Code session, read from the session's own transcript
(`<claude dir>/projects/<project>/<session id>.jsonl`, one JSON record per line, appended as the session runs).

A typed message is a record of `type` `user` that is not a tool result, not marked `isMeta`, `isCompactSummary` or
`isSidechain`, whose `origin` is absent or has `kind` `human` (other kinds: `peer`, `task-notification`) and whose
`promptSource` is absent, `typed` or `queued` (a message typed while the session was busy; `sdk` and `system` are
programs). A prompt the bridge sent has the same shape, so the ledger removes it. Only a time leaves this module."""

import json
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .jsonget import items, obj, text
from .ledger import Ledger, digest

SESSION_ID = re.compile(r"[0-9a-fA-F-]{36}")
CHUNK = 1 << 20


@dataclass(frozen=True)
class Typed:
    at: str  # the record's own ISO timestamp
    epoch: float
    digest: str  # of its text, empty when it had none (an image alone)


def typed_entry(line: bytes) -> Typed | None:
    """The typed message a transcript line records, or None for any other line (or one that does not parse)."""
    if b'"type":"user"' not in line or b'"type":"tool_result"' in line:
        return None
    try:
        record = obj(json.loads(line))
    except ValueError:
        return None
    origin = obj(record.get("origin"))
    message = obj(record.get("message"))
    if record.get("type") != "user" or any(record.get(k) for k in ("isMeta", "isCompactSummary", "isSidechain")):
        return None
    if record.get("origin") is not None and origin.get("kind") != "human":
        return None
    if record.get("promptSource") not in (None, "typed", "queued"):
        return None
    content = message.get("content")
    if isinstance(content, str):
        body = content
    else:
        blocks = items(content)
        if not blocks or any(b.get("type") == "tool_result" for b in blocks):
            return None
        body = "".join(text(b, "text") or "" for b in blocks)
    stamp = text(record, "timestamp")
    if stamp is None:
        return None
    try:
        epoch = datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None
    return Typed(stamp, epoch, digest(body) if body.strip() else "")


def latest(times: list[str | None]) -> str | None:
    """The latest of the ISO times given, None when there is none."""
    known = [t for t in times if t is not None]
    return max(known, key=lambda t: datetime.fromisoformat(t).timestamp(), default=None)


def lines_backward(path: Path, start: int, end: int) -> Iterator[bytes]:
    """The lines of `path` between byte offsets `start` and `end` (both on line boundaries), last first."""
    with path.open("rb") as f:
        pos, carry = end, b""
        while pos > start:
            step = min(CHUNK, pos - start)
            pos -= step
            f.seek(pos)
            parts = (f.read(step) + carry).split(b"\n")
            carry = parts[0]
            yield from (p for p in reversed(parts[1:]) if p)
        if carry:
            yield carry


def complete_end(path: Path, size: int, floor: int) -> int:
    """The offset just past the last newline in the file, so a line still being written is left for the next read;
    `floor` when the last chunk holds none."""
    with path.open("rb") as f:
        begin = max(floor, size - CHUNK)
        f.seek(begin)
        tail = f.read(size - begin)
    cut = tail.rfind(b"\n")
    return floor if cut < 0 else begin + cut + 1


@dataclass
class Seen:
    """What one session's transcript held when last read: how far it was read, and the latest typed time found."""

    path: Path
    read_to: int
    last: str | None


class Transcripts:
    def __init__(self, projects: Path, ledger: Ledger) -> None:
        self.projects = projects
        self.ledger = ledger
        self.seen: dict[str, Seen] = {}
        self.lock = threading.Lock()

    def last_typed(self, session_id: str) -> str | None:
        """The ISO time of the latest message a person typed into the session, None when there is none or the
        transcript cannot be read. Only the bytes added since the last call are read."""
        path = self.find(session_id)
        if path is None:
            return None
        try:
            size = path.stat().st_size
            with self.lock:
                before = self.seen.get(session_id)
                known = before if before is not None and before.path == path and before.read_to <= size else None
                start = known.read_to if known else 0
                end = complete_end(path, size, start)
                found = self.latest(session_id, path, start, end)
                self.seen[session_id] = Seen(path, end, found or (known.last if known else None))
                return self.seen[session_id].last
        except OSError:
            return None

    def latest(self, session_id: str, path: Path, start: int, end: int) -> str | None:
        for line in lines_backward(path, start, end):
            entry = typed_entry(line)
            if entry is not None and not self.ledger.was_sent(session_id, entry.digest, entry.epoch):
                return entry.at
        return None

    def find(self, session_id: str) -> Path | None:
        """The newest transcript of the session across the projects, None for an id that is not a UUID."""
        if SESSION_ID.fullmatch(session_id) is None:
            return None
        try:
            found = [p for p in self.projects.glob(f"*/{session_id}.jsonl") if p.is_file()]
            return max(found, key=lambda p: p.stat().st_mtime, default=None)
        except OSError:
            return None
