"""What the tool loop checks around a step: whether a running one ends within a budget, whether the turn stops to
escalate, whether the deadline has passed."""

import asyncio
import logging
import math

from .. import logs
from ..inference.model import Entry
from . import aside
from .escalation import Escalating, Escalation
from .pace import Pace

turn_log = logging.getLogger("ashley.channels")


async def ends_within[T](running: asyncio.Future[T], seconds: float) -> bool:
    """Whether `running` is done within `seconds`, never cancelling it."""
    done, _ = await asyncio.wait((running,), timeout=None if seconds == math.inf else seconds)
    return bool(done)


def limit_stop(escalation: Escalation | None, hold: bool, pace: Pace, rounds: int, calls: int,
                entries: list[Entry]) -> Escalating | None:
    """`Escalating` when the turn escalates, has made calls and is at `max_tool_rounds` or `deadline_s` with no answer;
    with `hold`, only when it has an aside to say while the stronger route works."""
    limits = pace.limits
    if escalation is None or not calls or not (rounds >= limits.max_tool_rounds or pace.past(limits.deadline_s)):
        return None
    line = aside.latest(entries) if hold else None
    return None if hold and line is None else Escalating("a", tuple(entries), rounds, calls, line)


def late(pace: Pace, rounds: int, conversation_id: int | None) -> bool:
    """Whether the deadline has passed before a step that would otherwise offer tools, logged when it has."""
    if rounds >= pace.limits.max_tool_rounds or not pace.past(pace.limits.deadline_s):
        return False
    logs.info(turn_log, "respond.deadline", conversation=conversation_id, rounds=rounds, duration_ms=pace.ms())
    return True
