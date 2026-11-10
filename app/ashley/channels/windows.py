"""A turn's fresh windows (`Limits.windows`): when work is still going at `deadline_s`, its pace starts again instead of
the turn closing."""

import logging

from .. import logs
from .pace import Pace
from .steps import Steps

turn_log = logging.getLogger("ashley.channels")


async def taken(pace: Pace, steps: Steps, rounds: int, calls: int, conversation_id: int | None,
                closing: bool = False) -> bool:
    """Whether the turn took a fresh window, `pace` restarted and the window recorded: it has windows left and rounds
    to use them, and either a closing reply that was not the answer asks for it or it has made calls and is past
    `deadline_s`."""
    limits = pace.limits
    if pace.windows >= limits.windows or rounds >= limits.max_tool_rounds:
        return False
    if not closing and not (calls and pace.past(limits.deadline_s)):
        return False
    await steps.windowed()
    logs.info(turn_log, "respond.window", conversation=conversation_id, windows=pace.windows + 1, rounds=rounds,
              duration_ms=pace.ms())
    pace.restart()
    return True
