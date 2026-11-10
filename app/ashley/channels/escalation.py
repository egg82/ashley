"""A turn that cannot finish on its fast route goes on, once, on the stronger one (`docs/decisions.md`, "A turn
escalates once"). Two things send it, both decided in code: the turn reaches its kind's `max_tool_rounds` or
`deadline_s` with no answer (`A`), or the fast model's reply sets `Reply.escalate` (`B`), a structured field whose value
is the line she says while the stronger route works. Only a kind whose limits say `escalates` does either, on a channel
that takes replies said after the response (`Landing.escalation`).

The turn goes on with the entries it has, under the limits of the route it escalated to (`brainstorm`'s, with the
kind's own reply length), as `Inference` task `escalated` (routes of `brainstorm`, a ledger task of its own, so the
rate and the cost of escalated calls are visible). It escalates once; on the stronger route, `tool_loop` ends a turn as
any other, with a wrap-up at its own limits. Logged `respond.escalated` with the conversation, the trigger, the rounds
made, the task it left (`from_route`) and the task it went to (`to_route`) and duration_ms."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from ..conversations.model import Kind
from ..inference.model import Entry, Task
from .limits import Limits

Trigger = Literal["a", "b"]
"""`a`: the turn reached `max_tool_rounds` or `deadline_s` with no answer. `b`: the fast model's reply set
`Reply.escalate`."""

STRONGER: Kind = "brainstorm"
"""The kind whose limits the escalated turn takes; its model is the `escalated` task's routes, `routes.json`."""
TASK: Task = "escalated"


@dataclass(frozen=True)
class Escalation:
    """What a turn goes on with once it escalates: `limits`, its turn limits on the stronger route."""

    limits: Limits
    task: Task = TASK


@dataclass(frozen=True)
class Escalating:
    """The loop stopped to escalate, at `rounds` having made `calls`, after `entries`. `line` is what she says while the
    stronger route works: the reply's `escalate` (B), or her latest aside (A) when the loop was still to hold; None when
    A found the loop already held."""

    trigger: Trigger
    entries: tuple[Entry, ...]
    rounds: int
    calls: int
    line: str | None


def of(kind: Kind, limits: Mapping[Kind, Limits]) -> Escalation | None:
    """How a turn of `kind` escalates; None when its limits do not."""
    if not limits[kind].escalates:
        return None
    return Escalation(replace(limits[STRONGER], reply_chars=limits[kind].reply_chars, escalates=False))
