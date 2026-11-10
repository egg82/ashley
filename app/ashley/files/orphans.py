"""The keys the sweep's last pass found unreferenced and old enough, kept in Postgres (`file_orphans`) so the pass after
it may run on any pod of either site. `first_seen` is kept across passes for a key that stays."""

from .. import services
from ..db.database import Database


class PostgresCandidates:
    async def load(self) -> frozenset[str]:
        async with services.get(Database).connection() as conn:
            cur = await conn.execute("SELECT object_key FROM file_orphans")
            return frozenset(row[0] for row in await cur.fetchall())

    async def save(self, keys: frozenset[str]) -> None:
        """Make `keys` the candidates: the rest are dropped, those new are added."""
        wanted = sorted(keys)
        async with services.get(Database).connection() as conn:
            await conn.execute("DELETE FROM file_orphans WHERE NOT (object_key = ANY(%s))", (wanted,))
            await conn.execute("INSERT INTO file_orphans (object_key) SELECT unnest(%s::text[]) ON CONFLICT DO NOTHING",
                               (wanted,))
