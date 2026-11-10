"""A turn's work as its runner holds it (`docs/decisions.md`, "Work in flight survives its pod"). `begin` gives a turn
on a channel that takes replies said after the response (`Inbound.later`) a `Saved`: its checkpoint is saved in
`InFlight` as the loop goes, its claim renewed while it runs, a held line stored under the claim, and her turn stored
with the work's end in one transaction, together with queueing it in the `Outbox` when it goes out that way. Any other
turn gets `Unsaved`, which records nothing and stores her turn as before.

Logs `respond.claim_lost` with the person turn's id and why (`taken`, or `unreachable` when no renewal succeeded for
two thirds of a claim) when a run is stopped for losing its claim, and `respond.work_undropped` when work could not be
deleted after its turn failed."""

import asyncio
import logging
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import replace
from typing import Any, TypeVar

from .. import logs, services
from ..conversations.conversations import ConversationClosed, Conversations
from ..conversations.inflight import Claim, ClaimLost, InFlight, InFlightUnavailable, Leaving
from ..conversations.model import AgreedOutcome, NewTurn, Turn
from ..inference.model import Entry, Message, ToolCall, ToolCalls, ToolResult
from ..tools.action_judge import Verdict
from . import keep, steering
from .checkpoint import Acting, Checkpoint, dumps
from .dropping import dropped as dropped
from .escalation import Trigger
from .keep import Act
from .model import Inbound, on_bench
from .outbox import Outbox, Pushed
from .tool_loop import Progress, Steps

log = logging.getLogger("ashley.channels")
T = TypeVar("T")


class Unstored(Exception):
    """Her turn could not be stored (the conversation closed, or the turn was refused), so the reply is not sent; its
    work was dropped. `cause` is what refused it; `check` is the refusal's fixed wording when it was a `ValueError`
    (`postgres_queries.checked`: "a turn has text"), else empty."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(type(cause).__name__)
        self.cause = type(cause).__name__
        self.check = str(cause) if isinstance(cause, ValueError) else ""


class Work(Steps):
    """A turn's work in its runner's hands."""

    async def guarded(self, work: Coroutine[Any, Any, T]) -> T:
        """`work`'s result, run while the claim is renewed. Raises what `work` raises; ClaimLost when the run was
        stopped for losing its claim."""
        return await work

    async def say(self, conversation_id: int, turn: NewTurn) -> Turn:
        """Her turn said while the work goes on (a held line) stored, the work kept. Raises what
        `Conversations.add_turn` raises, and ClaimLost."""
        return await services.get(Conversations).add_turn(conversation_id, turn)

    async def store(self, conversation_id: int, turn: NewTurn, pushed: Sequence[Pushed] = (),
                    act: Act | None = None) -> Turn:
        """Her turn stored, ending the work unless `act` is left to do (`act`), and each of `pushed` queued in the
        `Outbox` (an answer that goes out after the response, a copy to the phone). Raises what
        `Conversations.add_turn` raises, OutboxUnavailable, and ClaimLost."""
        for p in pushed:
            await services.get(Outbox).add(p.household_id, p.thread, p.outbound)
        return await services.get(Conversations).add_turn(conversation_id, turn)

    def answering(self, turn: NewTurn) -> NewTurn:
        """`turn`, her final answer, as it is stored: carrying what the turn was handed (`NewTurn.handed`) when its
        thread steers, so it is refused while a message left to the turn was not."""
        return turn

    async def drop(self) -> bool:
        """The work ended with no turn of hers; whether it is known to be gone, so no other runner will answer it.
        Never raises."""
        return True

    @property
    def retries(self) -> bool:
        """Whether the work outlives this run, so a runner that cannot finish it may keep it for another (`defer`)."""
        return False

    @property
    def unreachable_told(self) -> bool:
        """Whether the line that her thinking could not be reached is already said."""
        return True

    async def told_unreachable(self) -> None:
        """Record that the line is said."""

    async def defer(self, seconds: float) -> None:
        """Keep the work for another runner, which takes it no sooner than `seconds` from now. Raises ClaimLost,
        InFlightUnavailable."""

    async def act(self, conversation_id: int, said_id: int, hers: int | None, act: Act, household_id: int,
                  speaker_id: int | None) -> None:
        """`act`, which her stored turn `hers` asked of memory, carried out (`keep.now`) and the work ended."""
        await keep.now(conversation_id, said_id, hers, act, household_id, speaker_id)


class Unsaved(Work):
    """A turn that is not checkpointed: nothing survives its pod, so its taint lives here alone."""

    def __init__(self, taint: str | None = None) -> None:
        self._taint = taint
        self._changed = False
        self._windows = 0
        self._cut_off = 0
        self._judged: dict[str, Verdict] = {}

    @property
    def taint(self) -> str | None:
        return self._taint

    @property
    def changed(self) -> bool:
        return self._changed

    async def starting(self, call: ToolCall) -> None:
        self._changed = True

    @property
    def windows(self) -> int:
        return self._windows

    async def windowed(self) -> None:
        self._windows += 1

    @property
    def cut_off(self) -> int:
        return self._cut_off

    async def cut(self) -> None:
        self._cut_off += 1

    async def tainted(self, tool: str) -> bool:
        first = self._taint is None
        self._taint = tool if first else self._taint
        return first

    async def judged(self, call_id: str, verdict: Verdict) -> None:
        self._judged[call_id] = verdict

    def judgement(self, call_id: str) -> Verdict | None:
        return self._judged.get(call_id)


async def begin(inbound: Inbound, checkpoint: Checkpoint) -> Work:
    """The work of the turn `checkpoint` starts, logging `outside.tainted` with the conversation, the person turn and
    `by` the origin when it starts tainted. Raises InFlightUnavailable for a turn that is saved."""
    if checkpoint.tainted is not None:
        logs.info(log, "outside.tainted", conversation=checkpoint.conversation_id, turn=checkpoint.said_id,
                  by=checkpoint.tainted)
    if not inbound.later:
        return Unsaved(checkpoint.tainted)
    claim = await services.get(InFlight).begin(checkpoint.conversation_id, checkpoint.said_id, dumps(checkpoint))
    return Saved(claim, checkpoint)


class Saved(Work):
    """Work kept in `InFlight` under `claim`, its checkpoint saved as the loop records progress."""

    def __init__(self, claim: Claim, checkpoint: Checkpoint) -> None:
        self._claim = claim
        self._checkpoint = checkpoint

    @property
    def checkpoint(self) -> Checkpoint:
        return self._checkpoint

    async def asked(self, entries: tuple[Entry, ...], asked: ToolCalls, rounds: int, calls: int) -> None:
        await self._save(replace(self._checkpoint, progress=Progress(entries, rounds, calls, asked, {},
                                                                   self._checkpoint.progress.steered),
                                 started=frozenset()))

    async def starting(self, call: ToolCall) -> None:
        await self._save(replace(self._checkpoint, started=self._checkpoint.started | {call.id}, changed=True))

    @property
    def changed(self) -> bool:
        return self._checkpoint.changed

    async def ran(self, result: ToolResult) -> None:
        progress = self._checkpoint.progress
        done = {**progress.done, result.call_id: result}
        await self._save(replace(self._checkpoint, progress=replace(progress, done=done)))

    @property
    def taint(self) -> str | None:
        return self._checkpoint.tainted

    async def tainted(self, tool: str) -> bool:
        if self._checkpoint.tainted is not None:
            return False
        await self._save(replace(self._checkpoint, tainted=tool))
        return True

    async def judged(self, call_id: str, verdict: Verdict) -> None:
        await self._save(replace(self._checkpoint, judged={**self._checkpoint.judged, call_id: verdict}))

    def judgement(self, call_id: str) -> Verdict | None:
        return self._checkpoint.judged.get(call_id)

    @property
    def escalated(self) -> Trigger | None:
        return self._checkpoint.escalated

    @property
    def windows(self) -> int:
        return self._checkpoint.windows

    async def windowed(self) -> None:
        await self._save(replace(self._checkpoint, windows=self._checkpoint.windows + 1, worked_s=0.0))

    @property
    def cut_off(self) -> int:
        return self._checkpoint.cut_off

    async def cut(self) -> None:
        await self._save(replace(self._checkpoint, cut_off=self._checkpoint.cut_off + 1))

    async def worked(self, seconds: float) -> None:
        await self._save(replace(self._checkpoint, worked_s=seconds))

    async def escalate(self, trigger: Trigger) -> None:
        await self._save(replace(self._checkpoint, escalated=trigger))

    async def arrived(self, inbound: Inbound) -> None:
        await self._save(replace(self._checkpoint, inbound=inbound))

    async def carried(self, talk: int, ask: int) -> None:
        if self._checkpoint.carried != (talk, ask):
            await self._save(replace(self._checkpoint, carried=(talk, ask)))

    async def steer(self, entries: tuple[Entry, ...], rounds: int, calls: int) -> tuple[Message, ...]:
        """The messages handed to the turn since it last asked (`steering.hand`), saved in its checkpoint beside the
        entries they join, so a runner that resumes the turn has both and none twice."""
        c, where = self._checkpoint, self._steered()
        if where is None:
            return ()
        fresh = await steering.hand(c.inbound, where[0], where[1], c.progress.steered)
        if not fresh:
            return ()
        said = tuple(m for _, m in fresh)
        steered = (*c.progress.steered, *(i for i, _ in fresh))
        await self._save(replace(c, progress=Progress((*entries, *said), rounds, calls, None, {}, steered)))
        return said

    def answering(self, turn: NewTurn) -> NewTurn:
        if self._steered() is None:
            return turn
        return replace(turn, handed=self._checkpoint.progress.steered)

    def _steered(self) -> tuple[int, int] | None:
        """Where the turn is steered: the conversation and its turn the messages after which are the turn's to be
        handed. The bench talk its ask was carried into once it landed there; else its own, when its thread's messages
        steer and it has not moved to another bench."""
        c = self._checkpoint
        if c.carried is not None:
            return c.carried
        if not c.inbound.steers or c.inbound.lands_on is not None:
            return None
        return c.conversation_id, c.said_id

    async def guarded(self, work: Coroutine[Any, Any, T]) -> T:
        running = asyncio.ensure_future(work)
        lost: list[str] = []
        beating = asyncio.create_task(self._beat(running, lost))
        try:
            return await running
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if lost and (me is None or not me.cancelling()):
                logs.warning(log, "respond.claim_lost", said=self._claim.said_id, why=lost[0])
                raise ClaimLost() from None
            raise
        finally:
            beating.cancel()

    async def say(self, conversation_id: int, turn: NewTurn) -> Turn:
        """Stored only while the claim holds, so a runner that lost the turn never adds a line after another's
        answer. In another conversation than the claim's (a bench's talk the page moved to) the claim is renewed, which
        raises ClaimLost once it is lost, and the line added there."""
        if conversation_id == self._claim.conversation_id:
            return await services.get(InFlight).said(self._claim, turn)
        await services.get(InFlight).renew(self._claim)
        return await services.get(Conversations).add_turn(conversation_id, turn)

    async def store(self, conversation_id: int, turn: NewTurn, pushed: Sequence[Pushed] = (),
                    act: Act | None = None) -> Turn:
        """Stored and queued in one transaction (`Outbox.answer`), so a resumed answer goes out once; with `act`, the
        work is kept holding it (`Checkpoint.acting`), so the act survives this runner. Raises Unstored, the work
        dropped, when the conversation refuses the turn: a reply that cannot be stored is never delivered."""
        left: list[Checkpoint] = []
        kept = None if act is None else self._acting(act, left)
        try:
            if pushed:
                made = await services.get(Outbox).answer(self._claim, turn, pushed, kept)
            else:
                made = await services.get(InFlight).finish(self._claim, turn, kept)
        except (ConversationClosed, ValueError) as e:
            await self.drop()
            raise Unstored(e) from e
        if left:
            self._checkpoint = left[0]
        return made

    async def agreed(self, outcome: AgreedOutcome) -> None:
        """The work ended with `outcome` kept on its person turn and no turn of hers (`InFlight.agreed`)."""
        await services.get(InFlight).agreed(self._claim, outcome)

    def _acting(self, act: Act, left: list[Checkpoint]) -> Callable[[Turn], str]:
        """The checkpoint of the work left once her turn is stored, kept in `left` as well."""
        def after(stored: Turn) -> str:
            left.append(replace(self._checkpoint, acting=Acting(act, stored.id)))
            return dumps(left[0])
        return after

    async def act(self, conversation_id: int, said_id: int, hers: int | None, act: Act, household_id: int,
                  speaker_id: int | None) -> None:
        """Recorded begun before it runs, under the claim, and the work deleted after, so an act is never begun twice.
        Logs `respond.memory_act_deferred` with the person turn and the error when it could not be recorded begun,
        and leaves it for the runner that resumes the work."""
        acting = self._checkpoint.acting
        if acting is None:
            await super().act(conversation_id, said_id, hers, act, household_id, speaker_id)
            return
        try:
            await self._save(replace(self._checkpoint, acting=replace(acting, started=True)))
        except (ClaimLost, InFlightUnavailable) as e:
            logs.warning(log, "respond.memory_act_deferred", said=self._claim.said_id, error=type(e).__name__)
            return
        try:
            await self.guarded(keep.now(conversation_id, said_id, hers, act, household_id, speaker_id))
        except ClaimLost:
            return
        await self.drop()

    async def drop(self) -> bool:
        """A message left to the turn and not handed it gets work of its own (`InFlight.drop_leaving`)."""
        return await dropped(self._claim, self._leaving())

    @property
    def retries(self) -> bool:
        return True

    @property
    def unreachable_told(self) -> bool:
        return self._checkpoint.unreachable_told

    async def told_unreachable(self) -> None:
        await self._save(replace(self._checkpoint, unreachable_told=True))

    async def defer(self, seconds: float) -> None:
        await services.get(InFlight).defer(self._claim, seconds)

    async def begun(self, checkpoint: Checkpoint) -> None:
        """The work, claimed before anything was built (`Checkpoint.left`), now holding `checkpoint`. Raises ClaimLost,
        InFlightUnavailable."""
        await self._save(checkpoint)

    def _leaving(self) -> Leaving | None:
        c, where = self._checkpoint, self._steered()
        if where is None:
            return None

        def seed(turn: Turn) -> str:
            inbound = (replace(c.inbound, text=turn.text, speaker_id=turn.speaker_id, source=None, moved_to=None)
                       if c.carried is None or c.inbound.moved_to is None
                       else on_bench(c.inbound.household_id, turn.speaker_id, c.inbound.moved_to, turn.text))
            return dumps(Checkpoint(inbound, where[0], turn.id, turn.speaker_id, {}, Progress((), 0, 0), left=True))
        return Leaving(where[0], where[1], seed)

    async def _save(self, checkpoint: Checkpoint) -> None:
        await services.get(InFlight).save(self._claim, dumps(checkpoint))
        self._checkpoint = checkpoint

    async def _beat(self, running: asyncio.Future[Any], lost: list[str]) -> None:
        """Renew the claim every third of it until `running` ends; cancel it once the claim is lost."""
        inflight = services.get(InFlight)
        loop = asyncio.get_running_loop()
        renewed = loop.time()
        while True:
            await asyncio.sleep(inflight.claim_s / 3)
            try:
                await inflight.renew(self._claim)
                renewed = loop.time()
                continue
            except ClaimLost:
                lost.append("taken")
            except InFlightUnavailable:
                if loop.time() - renewed < inflight.claim_s * 2 / 3:
                    continue
                lost.append("unreachable")
            running.cancel()
            return
