"""TrustWriter in Postgres. One transaction per write: the person's revision row is made if missing and locked, the
version compared, their rows replaced, a log row written per changed kind and the log pruned."""

import logging
from collections.abc import Mapping

from .. import logs
from ..db.database import Database
from .kinds import Kinds, Value, load
from .postgres import translated, value_of
from .trust import StoredTrust, TrustUnavailable
from .trust_write import RETAIN_DAYS, TrustWriter, VersionConflict

log = logging.getLogger("ashley.trust")

PERSON = "SELECT 1 FROM people WHERE id = %(person)s AND household_id = %(household)s FOR KEY SHARE"
MADE = ("INSERT INTO trust_revisions (household_id, person_id, version) VALUES (%(household)s, %(person)s, 0) "
        "ON CONFLICT (person_id) DO NOTHING")
LOCK = "SELECT version FROM trust_revisions WHERE person_id = %(person)s AND household_id = %(household)s FOR UPDATE"
CURRENT = "SELECT kind, value FROM trust_settings WHERE person_id = %(person)s AND household_id = %(household)s"
CLEAR = "DELETE FROM trust_settings WHERE person_id = %(person)s AND household_id = %(household)s"
INSERT = ("INSERT INTO trust_settings (household_id, person_id, kind, value) "
          "VALUES (%(household)s, %(person)s, %(kind)s, %(value)s)")
BUMP = ("UPDATE trust_revisions SET version = version + 1, updated_at = now() "
        "WHERE person_id = %(person)s AND household_id = %(household)s RETURNING version, updated_at")
LOGGED = ("INSERT INTO trust_settings_log (household_id, person_id, kind, before, after) "
          "VALUES (%(household)s, %(person)s, %(kind)s, %(before)s, %(after)s)")
PRUNE = "DELETE FROM trust_settings_log WHERE changed_at < now() - make_interval(days => %(days)s)"


class PostgresTrustWriter(TrustWriter):
    def __init__(self, database: Database, kinds: Kinds | None = None) -> None:
        self._database = database
        self._kinds = kinds or load()

    async def put(self, household_id: int, person_id: int, version: int, chosen: Mapping[str, Value]) -> StoredTrust:
        kept = self._kinds.checked(chosen)
        args = {"person": person_id, "household": household_id}
        with translated():
            async with self._database.connection() as conn:
                if await (await conn.execute(PERSON, args)).fetchone() is None:
                    raise TrustUnavailable("no such person in the household")
                await conn.execute(MADE, args)
                held = await (await conn.execute(LOCK, args)).fetchone()
                assert held is not None
                if held[0] != version:
                    raise VersionConflict
                before = {r[0]: value_of(r[1]) for r in await (await conn.execute(CURRENT, args)).fetchall()}
                await conn.execute(CLEAR, args)
                for kind, value in sorted(kept.items()):
                    await conn.execute(INSERT, {**args, "kind": kind, "value": value})
                row = await (await conn.execute(BUMP, args)).fetchone()
                changed = sorted(k for k in before.keys() | kept.keys() if before.get(k) != kept.get(k))
                for kind in changed:
                    await conn.execute(LOGGED, {**args, "kind": kind, "before": before.get(kind), "after": kept.get(kind)})
                await conn.execute(PRUNE, {"days": RETAIN_DAYS})
        assert row is not None
        logs.info(log, "trust.changed", household=household_id, person=person_id, kinds=len(changed),
                  changed=",".join(changed), version=row[0])
        return StoredTrust(row[0], kept, row[1])
