"""Trust in Postgres, tables `trust_revisions` and `trust_settings`."""

from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .kinds import Value
from .trust import StoredTrust, Trust, TrustUnavailable

REVISION = "SELECT version, updated_at FROM trust_revisions WHERE person_id = %(person)s AND household_id = %(household)s"
VALUES = "SELECT kind, value FROM trust_settings WHERE person_id = %(person)s AND household_id = %(household)s"


@contextmanager
def translated() -> Generator[None]:
    """A database out of reach as TrustUnavailable."""
    try:
        yield
    except DatabaseUnavailable as e:
        raise TrustUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise TrustUnavailable("database unreachable") from e


def value_of(text: str) -> Value:
    return "act" if text == "act" else "offer"


class PostgresTrust(Trust):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def stored(self, household_id: int, person_id: int) -> StoredTrust:
        args = {"person": person_id, "household": household_id}
        with translated():
            async with self._database.connection() as conn:
                revision = await (await conn.execute(REVISION, args)).fetchone()
                rows = await (await conn.execute(VALUES, args)).fetchall()
        if revision is None:
            return StoredTrust()
        return StoredTrust(revision[0], {r[0]: value_of(r[1]) for r in rows}, revision[1])
