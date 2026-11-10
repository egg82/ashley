"""What every `Lease` implementation logs the same way: the first of a run of identical waits, and a body's outcome."""

import asyncio
import logging

from .. import logs

log = logging.getLogger("ashley.referee")


class Streak:
    """Logs the first of a run of identical events, so a standby waiting for hours writes one line, not thousands."""

    def __init__(self) -> None:
        self._last = ""

    def once(self, event: str, **fields: object) -> None:
        if event != self._last:
            logs.info(log, event, **fields)
        self._last = event

    def reset(self) -> None:
        self._last = ""


def outcome(task: asyncio.Task[None]) -> str:
    if task.cancelled() or task.exception() is not None:
        return "body_failed"
    return "body_returned"


def log_outcome(task: asyncio.Task[None], name: str, **fields: object) -> None:
    """A failed body's exception, logged with its frames (the body ran in its own task, so nothing else sees it)."""
    if task.cancelled():
        logs.error(log, "lease.body_failed", False, name=name, **fields, error="CancelledError")
        return
    try:
        task.result()
    except Exception:
        logs.error(log, "lease.body_failed", exc=True, name=name, **fields)
