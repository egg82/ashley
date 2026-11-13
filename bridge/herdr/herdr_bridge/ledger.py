"""The prompts the bridge itself sent, so a transcript entry that is one of them is not read as the person typing.
herdr pastes a prompt into the session, and Claude Code records the paste exactly as it records typing. Only a
digest of each text is kept, never the text."""

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .jsonget import obj, text

RETENTION_S = 7 * 24 * 3600
MAX_ENTRIES = 2000
EARLY_S = 5  # a transcript time may precede the send time by this much (clock read before the paste lands)
LATE_S = 300  # and follow it by this much (the session finishes what it was doing before it records the prompt)


def digest(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode()).hexdigest()


class Ledger:
    """One JSON line per sent prompt in `path`: the session, the digest and the send time in epoch seconds. Entries
    older than `RETENTION_S`, and all but the newest `MAX_ENTRIES`, are dropped whenever one is added."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()

    def record(self, session_id: str, prompt: str) -> None:
        now = self.clock()
        fresh = {"s": session_id, "h": digest(prompt), "t": now}
        with self.lock:
            kept = [e for e in self.read() if now - e[2] <= RETENTION_S][-(MAX_ENTRIES - 1):]
            lines = [json.dumps({"s": s, "h": h, "t": t}) for s, h, t in kept] + [json.dumps(fresh)]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            staged = self.path.with_name(self.path.name + ".new")
            staged.write_text("\n".join(lines) + "\n")
            os.replace(staged, self.path)

    def was_sent(self, session_id: str, prompt_digest: str, at: float) -> bool:
        """Whether the bridge sent this text to this session at about `at` (epoch seconds)."""
        with self.lock:
            return any(s == session_id and h == prompt_digest and -EARLY_S <= at - t <= LATE_S
                       for s, h, t in self.read())

    def read(self) -> list[tuple[str, str, float]]:
        try:
            raw = self.path.read_text().splitlines()
        except OSError:
            return []
        entries: list[tuple[str, str, float]] = []
        for line in raw:
            try:
                d = obj(json.loads(line))
            except ValueError:
                continue
            stamp = d.get("t")
            s, h = text(d, "s"), text(d, "h")
            if s is not None and h is not None and isinstance(stamp, (int, float)):
                entries.append((s, h, float(stamp)))
        return entries
