"""What the house eval needs from the live process: the household and person that ask, and the spend ledger's rows."""

import psycopg

from ..connections import address
from ..connections.connections import Connections
from ..db.database import Database
from ..home_assistant.homes import SCHEMES
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


async def connect_house(connections: Connections, seat: Seat, base_url: str, token: str) -> None:
    """Seal `base_url` and `token` as the seat's household's `home_assistant` connection, replacing the one it holds, so
    the run's house is what the caller names. Raises ValueError when either is empty, the address is not an http(s) one,
    or connections cannot be opened; ConnectionsUnavailable when the database refuses."""
    base = address.base_url(base_url, SCHEMES)
    if base is None or not token:
        raise ValueError("the house eval needs EVAL_HA_URL (an http or https address) and EVAL_HA_TOKEN")
    if not connections.can_open():
        raise ValueError("the house eval needs CONNECTIONS_KEY, to seal the house's connection")
    if await connections.seed(seat.household_id, "home_assistant", base, token) is not None:
        return
    held = [c for c in await connections.of_household(seat.household_id) if c.kind == "home_assistant"]
    await connections.replace(held[0].id, seat.household_id, seat.person_id, base, token)


def ledger(database: Database) -> Ledger:
    async def rows(conversation_id: int, task: str) -> list[Billed]:
        async with database.connection() as conn:
            got = await (await conn.execute(
                "SELECT coalesce(input_tokens, 0) + coalesce(cache_read_tokens, 0) + coalesce(cache_write_tokens, 0), "
                "provider, model FROM inference_calls WHERE conversation_id = %s AND task = %s AND outcome = 'ok' "
                "ORDER BY id", (conversation_id, task))).fetchall()
        return [Billed(int(r[0]), r[1], r[2]) for r in got]
    return rows
