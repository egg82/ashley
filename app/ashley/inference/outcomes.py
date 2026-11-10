"""What the spend ledger (`inference_calls`) says about how each provider answered lately."""

from collections.abc import Collection
from dataclasses import dataclass

from ..db.database import Database
from .model import TaskName


@dataclass(frozen=True)
class Share:
    """One provider's calls for one task in a window: `calls` rows, `failed` those whose outcome is in the failing set."""

    task: str
    provider: str
    calls: int
    failed: int

    @property
    def failed_share(self) -> float:
        return self.failed / self.calls


async def shares(database: Database, window_s: float, tasks: Collection[TaskName],
                 failing: Collection[str]) -> list[Share]:
    """Per (task, provider) among `tasks`, the calls recorded in the last `window_s` seconds (by the database's clock)
    and how many of them ended in one of `failing`, ordered by task and provider. A pair with no call is absent."""
    async with database.connection() as conn:
        rows = await (await conn.execute(
            "SELECT task, provider, count(*), count(*) FILTER (WHERE outcome = ANY(%s)) FROM inference_calls "
            "WHERE at > now() - make_interval(secs => %s) AND task = ANY(%s) "
            "GROUP BY task, provider ORDER BY task, provider",
            (list(failing), window_s, list(tasks)))).fetchall()
    return [Share(r[0], r[1], int(r[2]), int(r[3])) for r in rows]
