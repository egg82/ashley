"""Voices in Postgres: tables `voiceprints` (pgvector, no fixed dimension) and `voice_enrolments`."""

from datetime import datetime

import psycopg

from ...db.database import Database, DatabaseUnavailable
from ...inference.voiceprint import Voiceprint
from .voices import Enrolled, PersonPrints, UnknownEnrolee, Voices, VoicesUnavailable

_ARM = """
    INSERT INTO voice_enrolments (device_id, household_id, person_id, remaining, until)
    SELECT d.id, d.household_id, p.id, %(wakes)s, %(until)s FROM devices d
    JOIN people p ON p.household_id = d.household_id
    WHERE d.id = %(device)s AND p.id = %(person)s AND d.revoked_at IS NULL
    ON CONFLICT (device_id) DO UPDATE SET household_id = excluded.household_id, person_id = excluded.person_id,
        remaining = excluded.remaining, until = excluded.until, created_at = now()
    RETURNING device_id"""

# Under READ COMMITTED a second wake's UPDATE waits on the first's row lock and re-checks `remaining > 0`, so the last
# wake is taken once.
_TAKE = """
    UPDATE voice_enrolments SET remaining = remaining - 1
    WHERE device_id = %s AND remaining > 0 AND until > now()
    RETURNING household_id, person_id, remaining"""


class PostgresVoices(Voices):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def prints(self, household_id: int, model: str) -> tuple[PersonPrints, ...]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT person_id, vector::real[] FROM voiceprints WHERE household_id = %s AND model = %s "
                    "ORDER BY person_id, created_at, id",
                    (household_id, model),
                )
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise VoicesUnavailable("database unreachable") from e
        people: dict[int, list[tuple[float, ...]]] = {}
        for person_id, vector in rows:
            people.setdefault(person_id, []).append(tuple(vector))
        return tuple(PersonPrints(person_id, tuple(vectors)) for person_id, vectors in people.items())

    async def arm(self, device_id: int, person_id: int, wakes: int, until: datetime) -> None:
        if wakes < 1:
            raise ValueError("an enrolment needs at least one wake")
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(_ARM, {"device": device_id, "person": person_id, "wakes": wakes,
                                                "until": until})
                row = await cur.fetchone()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise VoicesUnavailable("database unreachable") from e
        if row is None:
            raise UnknownEnrolee("no unrevoked device and person in one household")

    async def enrol(self, device_id: int, voiceprint: Voiceprint) -> Enrolled | None:
        try:
            async with self._database.connection() as conn:
                await conn.execute("DELETE FROM voice_enrolments WHERE device_id = %s AND until <= now()",
                                   (device_id,))
                cur = await conn.execute(_TAKE, (device_id,))
                row = await cur.fetchone()
                if row is None:
                    return None
                household_id, person_id, remaining = row
                await conn.execute(
                    "INSERT INTO voiceprints (household_id, person_id, model, vector, device_id) "
                    "VALUES (%s, %s, %s, %s::vector, %s)",
                    (household_id, person_id, voiceprint.model, _literal(voiceprint.vector), device_id),
                )
                if remaining == 0:
                    await conn.execute("DELETE FROM voice_enrolments WHERE device_id = %s", (device_id,))
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise VoicesUnavailable("database unreachable") from e
        return Enrolled(person_id, remaining)

    async def forget(self, person_id: int) -> int:
        try:
            async with self._database.connection() as conn:
                await conn.execute("DELETE FROM voice_enrolments WHERE person_id = %s", (person_id,))
                cur = await conn.execute("DELETE FROM voiceprints WHERE person_id = %s", (person_id,))
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise VoicesUnavailable("database unreachable") from e
        return cur.rowcount


def _literal(vector: tuple[float, ...]) -> str:
    return "[" + ",".join(repr(x) for x in vector) + "]"
