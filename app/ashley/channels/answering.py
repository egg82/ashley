"""Her answer stored only once the turn was handed every message left to it (`docs/decisions.md`, "A message on a bench
steers the running turn"). A message stored after the turn's last hand and before her answer refuses the answer
(`Unhanded`, `NewTurn.handed`); the turn is then handed it after her draft, as the loop hands one at its final step,
and goes on from there."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace

from ..conversations.conversations import Unhanded
from ..inference.model import Message, SystemPrompt, ToolSpec
from ..inference.reply import Reply
from . import tool_loop, unsaid
from .escalation import Escalation
from .inflight import Work
from .landing import Landing
from .model import Medium
from .tool_loop import Answer, Arrive, Progress


@dataclass(frozen=True)
class Going:
    """How a turn goes on, as `tool_loop.resumed` takes it: its tool source `landing`, and the `system` and `tools` it
    began with (what `landing` moved it to replaces them), with asides when `asides`, and
    `escalation` when it escalates (`channels.escalation`)."""

    landing: Landing
    conversation_id: int
    system: Mapping[str, SystemPrompt]
    tools: tuple[ToolSpec, ...]
    asides: bool
    started: float
    arrive: Arrive
    medium: Medium
    escalation: Escalation | None = None


async def stored(work: Work, answer: Answer, store: Callable[[Reply], Awaitable[None]], going: Going) -> Answer:
    """`answer` stored by `store`; while `store` raises Unhanded, the turn handed what it missed after her draft
    (`Work.steer`) and gone on as `going` says, and that answer stored instead. The answer stored. Raises
    `unsaid.Unworded` for an answer of only `unsaid.Said` words on a paged channel with no receipts to show."""
    while True:
        closed = replace(answer, reply=await going.landing.closing(answer.reply))
        if isinstance(closed.reply, unsaid.Said) and going.landing.inbound.paged and going.landing.receipts is None:
            raise unsaid.Unworded(closed.reply.why)
        try:
            await store(closed.reply)
            return closed
        except Unhanded:
            draft = (*answer.entries, Message("ashley", answer.reply.text))
            said = await work.steer(draft, answer.rounds, answer.calls)
            answer = await _gone_on(work, Progress((*draft, *said), answer.rounds, answer.calls), going)


async def _gone_on(work: Work, progress: Progress, going: Going) -> Answer:
    now = going.landing.current(going.tools, going.system)
    return await work.guarded(tool_loop.resumed(
        progress, going.landing.kind, now.system, now.tools, going.landing.limits, going.conversation_id,
        going.landing, going.asides, going.started, steps=work, arrive=going.arrive, medium=going.medium,
        escalation=going.escalation))
