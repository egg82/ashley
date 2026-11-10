"""What the house eval needs from the live process: the household and person that ask, and the spend ledger's rows."""

import psycopg

from ..db.database import Database
from ..people import admin
from .house import Billed, Ledger, Seat

NAME = "house-eval"


def seat(database_url: str) -> Seat:
    """The eval's own household and person, made on first use. Writes to the database it is pointed at, so run it
    against a scratch database."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        found = conn.execute("SELECT h.id, (SELECT min(p.id) FROM people p WHERE p.household_id = h.id) "
                             "FROM households h WHERE h.name = %s", (NAME,)).fetchone()
        if found and found[1] is not None:
            return Seat(found[0], found[1])
        household = found[0] if found else admin.add_household(conn, NAME, "America/Denver")
        return Seat(household, admin.add_person(conn, household, "Eval"))


def ledger(database: Database) -> Ledger:
    async def rows(conversation_id: int, task: str) -> list[Billed]:
        async with database.connection() as conn:
            got = await (await conn.execute(
                "SELECT coalesce(input_tokens, 0) + coalesce(cache_read_tokens, 0) + coalesce(cache_write_tokens, 0), "
                "provider, model FROM inference_calls WHERE conversation_id = %s AND task = %s AND outcome = 'ok' "
                "ORDER BY id", (conversation_id, task))).fetchall()
        return [Billed(int(r[0]), r[1], r[2]) for r in got]
    return rows
