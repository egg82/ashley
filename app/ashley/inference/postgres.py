"""The spend ledger in Postgres: table `inference_calls`, one row per call, never updated or deleted by the app.

Columns: `id` (identity), `at` (timestamptz, the database's clock), `task`, `provider`, `model`, `outcome` (each
`text`, `task` and `outcome` checked against their Literals), `input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `audio_ms`, `characters` (`integer`; the app writes all six usage columns or none, NULL when usage is unknown, else all >= 0),
`cost_usd` (`numeric`, NULL when unknown, else >= 0, stored exactly), `duration_ms` (`integer` >= 0), `conversation_id`
(`bigint`, NULL when the call served no conversation; no foreign key, so it may name a conversation long gone)."""

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from ..db.database import Database
from .model import TaskName
from .spend import Call, SpendLedger


@dataclass(frozen=True)
class Spent:
    """What a set of ledger rows cost: `calls` rows, `cost_usd` the sum over those with a cost, `unpriced` how many
    had none, so `cost_usd` alone understates the spend whenever `unpriced` is above 0."""

    calls: int
    cost_usd: Decimal
    unpriced: int


@dataclass(frozen=True)
class SpentBy:
    """`Spent` for the rows of one (task, provider, model, outcome)."""

    task: str
    provider: str
    model: str
    outcome: str
    spent: Spent


class PostgresSpendLedger(SpendLedger):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def record(self, call: Call) -> None:
        usage = call.usage
        async with self._database.connection() as conn:
            await conn.execute(
                "INSERT INTO inference_calls (task, provider, model, outcome, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, audio_ms, characters, cost_usd, duration_ms, conversation_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (call.task, call.provider, call.model, call.outcome,
                 usage and usage.input_tokens, usage and usage.output_tokens,
                 usage and usage.cache_read_tokens, usage and usage.cache_write_tokens,
                 usage and usage.audio_ms, usage and usage.characters, call.cost_usd, call.duration_ms,
                 call.conversation_id),
            )


async def last_call_id(database: Database) -> int:
    """The newest ledger row's id, 0 when there are none: a mark to read `spent_after` from."""
    async with database.connection() as conn:
        row = await (await conn.execute("SELECT coalesce(max(id), 0) FROM inference_calls")).fetchone()
    return int(row[0]) if row else 0


async def spent_after(database: Database, after_id: int, tasks: Collection[TaskName]) -> Spent:
    """The spend of the ledger rows for `tasks` whose id is above `after_id`."""
    async with database.connection() as conn:
        row = await (await conn.execute(
            "SELECT count(*), coalesce(sum(cost_usd), 0), count(*) FILTER (WHERE cost_usd IS NULL) "
            "FROM inference_calls WHERE id > %s AND task = ANY(%s)", (after_id, list(tasks)))).fetchone()
    return Spent(int(row[0]), Decimal(row[1]), int(row[2])) if row else Spent(0, Decimal(0), 0)


async def spent_by_after(database: Database, after_id: int, tasks: Collection[TaskName]) -> list[SpentBy]:
    """`spent_after`, one entry per (task, provider, model, outcome), ordered by those."""
    async with database.connection() as conn:
        rows = await (await conn.execute(
            "SELECT task, provider, model, outcome, count(*), coalesce(sum(cost_usd), 0), "
            "count(*) FILTER (WHERE cost_usd IS NULL) FROM inference_calls WHERE id > %s AND task = ANY(%s) "
            "GROUP BY task, provider, model, outcome ORDER BY task, provider, model, outcome",
            (after_id, list(tasks)))).fetchall()
    return [SpentBy(r[0], r[1], r[2], r[3], Spent(int(r[4]), Decimal(r[5]), int(r[6]))) for r in rows]
