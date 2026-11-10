"""Accounts in Postgres. One statement per call, so a link racing another for the same external id cannot map it to
both people: the unique (system, external_id) decides."""

from ..db.database import Database
from .accounts import Accounts, Linked
from .model import Account
from .postgres import translated

_LINK = (
    "WITH made AS (INSERT INTO accounts (household_id, person_id, system, external_id, handle) "
    "SELECT household_id, id, %(system)s, %(external_id)s, %(handle)s FROM people WHERE id = %(person)s "
    "ON CONFLICT (system, external_id) DO UPDATE SET handle = excluded.handle "
    "WHERE accounts.person_id = excluded.person_id RETURNING id) "
    "SELECT count(*) FROM made"
)


class PostgresAccounts(Accounts):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def of(self, person_id: int) -> tuple[Account, ...]:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, household_id, person_id, system, external_id, handle FROM accounts "
                    "WHERE person_id = %s ORDER BY id", (person_id,))
                rows = await cur.fetchall()
        return tuple(Account(*r) for r in rows)

    async def link(self, person_id: int, system: str, external_id: str, handle: str) -> Linked:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(_LINK, {"system": system, "external_id": external_id, "handle": handle,
                                                 "person": person_id})
                row = await cur.fetchone()
        return "linked" if row is not None and row[0] == 1 else "taken"

    async def unlink(self, person_id: int, account_id: int, system: str) -> bool:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "DELETE FROM accounts WHERE id = %s AND person_id = %s AND system = %s",
                    (account_id, person_id, system))
        return cur.rowcount == 1
