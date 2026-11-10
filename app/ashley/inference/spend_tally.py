"""What the spend ledger holds for a span, read per provider and task (table `inference_calls`, `postgres`)."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..db.database import Database
from .spend_windows import Window, WindowName


@dataclass(frozen=True)
class Tally:
    """The rows of one (span, provider, task). `metered` of the `calls` reported usage and `priced` of them had a cost,
    so the sums cover only those rows: a token sum is None when `metered` is 0 and `cost_usd` is None when `priced` is
    0, never 0. `metered` less `priced` is the calls that had usage and no price."""

    window: WindowName
    provider: str
    task: str
    calls: int
    metered: int
    priced: int
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    audio_ms: int | None
    characters: int | None
    cost_usd: Decimal | None


_SQL = (
    "SELECT w.name, c.provider, c.task, count(*), count(c.input_tokens), count(c.cost_usd), sum(c.input_tokens), "
    "sum(c.output_tokens), sum(c.cache_read_tokens), sum(c.cache_write_tokens), sum(c.audio_ms), sum(c.characters), "
    "sum(c.cost_usd) FROM inference_calls c JOIN unnest(%s::text[], %s::timestamptz[]) AS w(name, starts) "
    "ON c.at >= w.starts GROUP BY w.name, c.provider, c.task ORDER BY c.provider, c.task, w.name")


async def tally(database: Database, spans: Sequence[Window]) -> list[Tally]:
    """One entry per (span, provider, task) that has at least one call from the span's start to now, ordered by provider,
    task and span name. Raises `DatabaseUnavailable`."""
    async with database.connection() as conn:
        rows = await (await conn.execute(_SQL, ([w.name for w in spans], [w.starts for w in spans]))).fetchall()
    return [Tally(r[0], r[1], r[2], int(r[3]), int(r[4]), int(r[5]), _int(r[6]), _int(r[7]), _int(r[8]), _int(r[9]),
                  _int(r[10]), _int(r[11]), None if r[12] is None else Decimal(r[12])) for r in rows]


def _int(value: int | None) -> int | None:
    return None if value is None else int(value)
