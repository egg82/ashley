"""People in Postgres. One transaction per call; a read of several tables sees one snapshot."""

import logging
from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from .model import Account, Household, Person
from .people import People, PeopleUnavailable

log = logging.getLogger("ashley.people")


@contextmanager
def translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise PeopleUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise PeopleUnavailable("database unreachable") from e


class PostgresPeople(People):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def household(self, household_id: int) -> Household | None:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cur = await conn.execute(
                    "SELECT id, name, timezone, profile, locale, unit_system, clock FROM households WHERE id = %s", (household_id,))
                row = await cur.fetchone()
                if row is None:
                    return None
                cur = await conn.execute(
                    "SELECT id, household_id, name FROM people WHERE household_id = %s ORDER BY id", (household_id,))
                people = tuple(Person(*r) for r in await cur.fetchall())
        return Household(row[0], row[1], row[2], row[3], people, row[4], row[5], row[6])

    async def person_for(self, system: str, external_id: str) -> Person | None:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT p.id, p.household_id, p.name FROM accounts a "
                    "JOIN people p ON p.id = a.person_id AND p.household_id = a.household_id "
                    "WHERE a.system = %s AND a.external_id = %s",
                    (system, external_id),
                )
                row = await cur.fetchone()
        return None if row is None else Person(*row)

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, household_id, person_id, system, external_id FROM accounts "
                    "WHERE household_id = %s AND system = %s ORDER BY id",
                    (household_id, system),
                )
                rows = await cur.fetchall()
        logs.info(log, "people.accounts", household=household_id, system=system, count=len(rows))
        return tuple(Account(*r) for r in rows)
