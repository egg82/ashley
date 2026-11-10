"""The memory write job: the singleton that learns from conversations once they go idle (`docs/decisions.md`, "Memory
is atomic facts in Postgres"). It runs under the lease, so on one site at a time; replies never wait on it.

Logs `memory.job.policy` with every setting when it starts; per tick `memory.job.tick` (`batch`, `written`, `skipped`,
`failed`, `embedded` the facts the backfill embedded, `stopped` naming why the tick ended early, `duration_ms`); per
conversation `memory.job.written` (its id, the turn it is now written through, ops by kind, the inserted fact ids),
`memory.job.skipped` (with `reason`) or
`memory.job.failed` (the exception's type as `error`, `failures` in a row, `held=true` once that reaches
`max_failures`, and for an unexpected exception its type chain and frames). Ids, counts and types only."""

import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib import resources

from .. import logs, services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..conversations.model import Kind as ConversationKind
from ..conversations.policy import Policy as ConversationsPolicy
from ..inference.inference import InferenceRefused, InferenceRejected, InferenceUnavailable
from ..people.people import PeopleUnavailable
from .memory import AlreadyWritten, FactWriter, Memory, MemoryUnavailable
from .model import Unwritten

log = logging.getLogger("ashley.memory.job")

NAME = "memory-write"


@dataclass(frozen=True)
class Policy:
    """`tick_s` is the pause between ticks; `batch` the most conversations one tick takes; `candidates` how many of the
    most similar current facts the writer decides against; `max_failures` how many refused writes in a row hold a
    conversation back until someone says something new in it; `embed_batch` how many facts without a current
    embedding one tick embeds, after the conversations."""

    tick_s: float
    batch: int
    candidates: int
    max_failures: int
    embed_batch: int


def load() -> Policy:
    """The policy shipped in `write_job.json` beside this module."""
    return Policy(**json.loads(resources.files("ashley.memory").joinpath("write_job.json").read_text()))


class _Stop(Exception):
    """Ends the tick: what every remaining conversation needs is down. Nothing more is marked; the next tick retries."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class WriteJob:
    """`run` is the lease body: a tick, then `policy.tick_s`, until cancelled. A tick takes up to `policy.batch`
    conversations that need a write, oldest first, and for each reads it, keeps only the turns after the one it was
    written through, reads the candidate facts, asks `writer`, and applies the ops with the watermark in one
    transaction. Inference or the database unavailable ends the tick with nothing marked. A refused write (a stale
    target, an inference refusal, anything unexpected) is recorded as a failure and the tick moves on. Cancellation (the lease lost)
    stops it wherever it is; a write it interrupts rolls back whole."""

    def __init__(self, writer: FactWriter, policy: Policy, conversations: ConversationsPolicy,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._writer = writer
        self._policy = policy
        self._idle: dict[ConversationKind, float] = {k: t.idle_after_s for k, t in conversations.timings.items()}
        self._now = now

    async def run(self) -> None:
        logs.info(log, "memory.job.policy", **asdict(self._policy))
        while True:
            await self.tick()
            await asyncio.sleep(self._policy.tick_s)

    async def tick(self) -> Counter[str]:
        """One tick; how many conversations were written, skipped and failed."""
        started = time.perf_counter()
        counts: Counter[str] = Counter()
        batch: tuple[Unwritten, ...] = ()
        stopped: str | None = None
        embedded = 0
        try:
            batch = await services.get(Memory).unwritten(self._idle, self._policy.batch, self._policy.max_failures)
            for item in batch:
                counts[await self._one(item)] += 1
            embedded = await services.get(Memory).embed_missing(self._policy.embed_batch)
        except _Stop as e:
            stopped = e.reason
        except MemoryUnavailable:
            stopped = "database_unavailable"
        logs.info(log, "memory.job.tick", batch=len(batch), written=counts["written"], skipped=counts["skipped"],
                  failed=counts["failed"], embedded=embedded, stopped=stopped,
                  duration_ms=int((time.perf_counter() - started) * 1000))
        return counts

    async def _one(self, item: Unwritten) -> str:
        """`_write`, with anything it did not expect counted as a failed write of this one conversation, so one bad
        conversation cannot stall the rest. Cancellation is not an Exception, so it still stops the job."""
        try:
            return await self._write(item)
        except (_Stop, MemoryUnavailable):
            raise
        except Exception as e:
            return await self._failed(item.household_id, item.conversation_id, item.newest_turn, type(e).__name__,
                                      unexpected=True)

    async def _write(self, item: Unwritten) -> str:
        """Writes one conversation: `written`, `skipped` or `failed`. Raises _Stop."""
        try:
            read = await services.get(Conversations).get(item.conversation_id)
        except ConversationsUnavailable as e:
            raise _Stop("database_unavailable") from e
        if read is None or read.state == "open":
            return _skipped(item.conversation_id, "missing" if read is None else "open")
        fresh = replace(read, turns=tuple(t for t in read.turns
                                          if t.id > (item.written_through or 0) and t.author != "household"))
        if not any(t.author == "person" for t in fresh.turns):
            return _skipped(read.id, "nothing_new")
        through = read.turns[-1].id
        try:
            known = await services.get(Memory).similar(fresh, self._policy.candidates)
            ops = await self._writer.decide(fresh, known, self._now())
            inserted = await services.get(Memory).apply(read.household_id, read.id, ops, self._now(), through,
                                                         item.written_through)
        except (ValueError, InferenceRefused, InferenceRejected) as e:
            return await self._failed(read.household_id, read.id, through, type(e).__name__)
        except InferenceUnavailable as e:
            raise _Stop("inference_unavailable") from e
        except (MemoryUnavailable, PeopleUnavailable) as e:
            raise _Stop("database_unavailable") from e
        except AlreadyWritten:
            return _skipped(read.id, "already_written")
        kinds = Counter(type(op).__name__.lower() for op in ops)
        logs.info(log, "memory.job.written", conversation=read.id, through=through, turns=len(fresh.turns),
                  known=len(known), add=kinds["add"], update=kinds["update"], invalidate=kinds["invalidate"],
                  forget=kinds["forget"], noop=kinds["noop"], inserted=",".join(str(i) for i in inserted))
        return "written"

    async def _failed(self, household_id: int, conversation_id: int, through: int, error: str,
                      unexpected: bool = False) -> str:
        """Records the failure toward the cap and logs it; an unexpected one at error level, with its traceback's
        frames (`logs.error`, never the message). Called inside the `except` block that caught it."""
        failures = await services.get(Memory).write_failed(household_id, conversation_id, through)
        fields: dict[str, object] = {"conversation": conversation_id, "through": through, "error": error,
                                     "failures": failures, "held": failures >= self._policy.max_failures}
        if unexpected:
            logs.error(log, "memory.job.failed", exc=True, **fields)
        else:
            logs.warning(log, "memory.job.failed", **fields)
        return "failed"


def _skipped(conversation_id: int, reason: str) -> str:
    logs.info(log, "memory.job.skipped", conversation=conversation_id, reason=reason)
    return "skipped"
