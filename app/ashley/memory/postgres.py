"""Memory in Postgres. One transaction per call."""

import logging
from collections import Counter
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg import errors

from .. import logs
from ..conversations.model import Conversation, Kind as ConversationKind
from ..db.database import Database, DatabaseUnavailable
from . import postgres_embeddings as e, postgres_queries as q, postgres_writes as w
from .memory import AlreadyWritten, Memory, MemoryUnavailable
from .model import Add, Asker, Fact, Forget, Held, Invalidate, Noop, Op, Recalled, Unwritten, Update
from .recall_policy import RecallPolicy, load as load_policy
from .vectors import Vectors

log = logging.getLogger("ashley.memory")

READ_ONLY_TRANSACTION = "25006"
_OP_NAMES: dict[type, str] = {Add: "add", Update: "update", Invalidate: "invalidate", Forget: "forget", Noop: "noop"}


class NotCurrent(ValueError):
    def __init__(self, target: int) -> None:
        super().__init__(f"fact {target} is not a current fact of the household")
        self.target = target


@contextmanager
def translated() -> Generator[None]:
    """A row the facts table refuses (a person or conversation of another household, a kind it does not know) is the
    caller's ValueError; nothing in that transaction was applied."""
    try:
        yield
    except DatabaseUnavailable as e:
        raise MemoryUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise MemoryUnavailable("database unreachable") from e
    except (errors.ForeignKeyViolation, errors.CheckViolation) as e:
        if not (e.diag.constraint_name or "").startswith(("facts_", "memory_writes_")):
            raise
        raise ValueError(f"the write breaks {e.diag.constraint_name}") from e
    except psycopg.Error as e:
        if e.sqlstate == READ_ONLY_TRANSACTION:
            raise MemoryUnavailable("database is not writable") from e
        raise


_PROBE = "which model embeds"


class PostgresMemory(Memory):
    """Recall is hybrid: the full-text matches (at most `policy.limit`) and the `policy.vector_k` facts nearest the
    query by embedding, among those the same visibility filter lets through. Embedding goes through `Inference`; when it
    cannot answer, recall, `similar` and a write still work on full-text alone, and a fact written meanwhile has no
    embedding until `embed_missing` makes one. `policy` defaults to the shipped `recall.json`."""

    def __init__(self, database: Database, policy: RecallPolicy | None = None) -> None:
        self._database = database
        self._policy = policy or load_policy()
        self._vectors = Vectors()

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        vector = await self._vectors.one(query, "query")
        with translated():
            async with self._database.connection() as conn:
                found = await q.recall(conn, asker, query, self._policy.limit, self._policy.vector_k, vector)
        logs.info(log, "memory.recall", household=asker.household_id, returned=len(found.recalled),
                  by_text=found.by_text, by_vector=len(found.recalled) - found.by_text, embedded=vector is not None,
                  facts=",".join(str(r.fact.id) for r in found.recalled))
        return found.recalled

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        with translated():
            async with self._database.connection() as conn:
                found = await q.profile(conn, asker)
        logs.info(log, "memory.profile", household=asker.household_id, returned=len(found),
                  facts=",".join(str(r.fact.id) for r in found))
        return found

    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        said = " ".join(t.text for t in conversation.turns if t.author == "person")
        if not said:
            return ()
        vector = await self._vectors.one(said, "query", conversation.id)
        with translated():
            async with self._database.connection() as conn:
                return await q.similar(conn, conversation.household_id, said, limit, self._policy.vector_k, vector)

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        inserted: list[int] = []
        forgotten = 0
        texts = [op.fact.text for op in ops if isinstance(op, Add | Update)]
        made = await self._vectors.of(texts, "passage", conversation_id)
        vectors = iter(made or [None] * len(texts))
        try:
            with translated():
                async with self._database.connection() as conn:
                    if written_through is not None and not await w.mark_written(
                            conn, household_id, conversation_id, written_through, written_from):
                        raise AlreadyWritten(conversation_id)
                    for op in ops:
                        vector = next(vectors) if isinstance(op, Add | Update) else None
                        forgotten += await _apply_one(conn, household_id, conversation_id, op, at, inserted, vector)
        except (ValueError, AlreadyWritten) as e:
            reason = "already_written" if isinstance(e, AlreadyWritten) else (
                "not_current" if isinstance(e, NotCurrent) else "constraint")
            logs.info(log, "memory.apply_refused", household=household_id, conversation=conversation_id,
                      reason=reason, target=e.target if isinstance(e, NotCurrent) else None)
            raise
        if inserted and made is None:
            logs.warning(log, "memory.write_unembedded", household=household_id,
                         facts=",".join(str(i) for i in inserted))
        counts = Counter(_OP_NAMES[type(op)] for op in ops)
        logs.info(log, "memory.apply", household=household_id, conversation=conversation_id,
                  **{name: counts[name] for name in _OP_NAMES.values()}, deleted=forgotten,
                  inserted=",".join(str(i) for i in inserted), written_through=written_through)
        return tuple(inserted)

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        with translated():
            async with self._database.connection() as conn:
                return await q.held(conn, household_id, person_id, fact_id)

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        with translated():
            async with self._database.connection() as conn:
                deleted = await q.forget(conn, household_id, fact_id)
        if deleted is None:
            logs.info(log, "memory.forget_refused", household=household_id, by=by, reason="not_current",
                      target=fact_id)
            raise NotCurrent(fact_id)
        logs.info(log, "memory.forgotten", household=household_id, by=by, deleted=deleted)
        return deleted

    async def embed_missing(self, limit: int) -> int:
        model = self._vectors.model
        if model is None and await self._vectors.one(_PROBE, "query") is None:
            return 0
        model = self._vectors.model
        assert model is not None
        with translated():
            async with self._database.connection() as conn:
                wanted = await e.missing(conn, model, limit)
        made = await self._vectors.of([text for _, text in wanted], "passage")
        if not wanted or made is None:
            return 0
        stored = 0
        with translated():
            async with self._database.connection() as conn:
                for (fact_id, _), vector in zip(wanted, made, strict=True):
                    stored += await e.store(conn, fact_id, vector)
        logs.info(log, "memory.embed_backfill", wanted=len(wanted), stored=stored, model=model)
        return stored

    async def unwritten(self, idle_after_s: Mapping[ConversationKind, float], limit: int,
                        max_failures: int) -> tuple[Unwritten, ...]:
        with translated():
            async with self._database.connection() as conn:
                return await w.unwritten(conn, idle_after_s, limit, max_failures)

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        with translated():
            async with self._database.connection() as conn:
                return await w.write_failed(conn, household_id, conversation_id, through)

    async def written_through(self, conversation_id: int) -> int | None:
        with translated():
            async with self._database.connection() as conn:
                return await w.written_through(conn, conversation_id)


async def _apply_one(conn: q.Connection, household_id: int, conversation_id: int, op: Op, at: datetime,
                     inserted: list[int], vector: q.Vector | None) -> int:
    """Carries out one op, appending any fact it inserts to `inserted`, stored with `vector`; returns how many facts
    it deleted."""
    match op:
        case Add(fact):
            inserted.append(await q.insert(conn, household_id, conversation_id, fact, at, vector))
        case Update(target, fact):
            inserted.append(await q.insert(conn, household_id, conversation_id, fact, at, vector))
            if not await q.close(conn, household_id, target, at, inserted[-1]):
                raise NotCurrent(target)
        case Invalidate(target):
            if not await q.close(conn, household_id, target, at, None):
                raise NotCurrent(target)
        case Forget(target):
            deleted = await q.forget(conn, household_id, target)
            if deleted is None:
                raise NotCurrent(target)
            return deleted
        case Noop():
            pass
    return 0
