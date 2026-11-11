"""Admins in Postgres. Each write takes one transaction-scoped advisory lock before its conditional write: under READ
COMMITTED a statement's "no other admin" check sees only what had committed when it began, so two at once would both
pass it; behind the lock each statement starts after the last writer committed."""

import logging

from .. import logs
from ..db.database import Database
from .admins import Admins, Outcome
from .postgres import translated

log = logging.getLogger("ashley.people")
_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('people:admin', 0))"
_ENSURE = (
    "UPDATE people SET admin = true WHERE id = (SELECT min(id) FROM people WHERE household_id = %s) "
    "AND NOT EXISTS (SELECT 1 FROM people WHERE admin) RETURNING id"
)
_GRANT = "UPDATE people SET admin = true WHERE id = %s AND household_id = %s RETURNING old.admin"
_REVOKE = (
    "UPDATE people SET admin = false WHERE id = %(id)s AND household_id = %(household)s "
    "AND (NOT admin OR EXISTS (SELECT 1 FROM people WHERE admin AND id <> %(id)s)) RETURNING old.admin"
)
_EXISTS = "SELECT 1 FROM people WHERE id = %s AND household_id = %s"


class PostgresAdmins(Admins):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_one(self, household_id: int) -> int | None:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute(_LOCK)
                row = await (await conn.execute(_ENSURE, (household_id,))).fetchone()
        if row is None:
            return None
        logs.info(log, "people.admin_granted", person=row[0], by="none_left")
        made: int = row[0]
        return made

    async def put(self, household_id: int, person_id: int, admin: bool, by: int) -> Outcome:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute(_LOCK)
                if admin:
                    cur = await conn.execute(_GRANT, (person_id, household_id))
                else:
                    cur = await conn.execute(_REVOKE, {"id": person_id, "household": household_id})
                row = await cur.fetchone()
                found = row is not None or (await (await conn.execute(_EXISTS, (person_id, household_id))).fetchone()
                                            is not None)
        if row is None:
            return "last_admin" if found else "not_found"
        if row[0] != admin:
            logs.info(log, "people.admin_granted" if admin else "people.admin_revoked", person=person_id, by=by)
        return "set"
