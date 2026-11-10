"""A household's own fields written in Postgres: one UPDATE that answers both the old and new row, so the log line names
what changed without a second read racing another write."""

import logging
from dataclasses import fields

from .. import logs
from ..db.database import Database
from .household_write import HouseholdWriter
from .model import Household, HouseholdEdit, Person
from .postgres import translated

log = logging.getLogger("ashley.people")
_FIELDS = tuple(f.name for f in fields(HouseholdEdit))
_PUT = (
    "UPDATE households SET timezone = %(timezone)s, profile = %(profile)s, locale = %(locale)s, "
    "unit_system = %(unit_system)s, clock = %(clock)s WHERE id = %(id)s "
    "RETURNING new.name, old.timezone, new.timezone, old.profile, new.profile, old.locale, new.locale, "
    "old.unit_system, new.unit_system, old.clock, new.clock"
)


class PostgresHouseholdWriter(HouseholdWriter):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def put(self, household_id: int, person_id: int, edit: HouseholdEdit) -> Household | None:
        args = {f: getattr(edit, f) for f in _FIELDS}
        with translated():
            async with self._database.connection() as conn:
                row = await (await conn.execute(_PUT, {**args, "id": household_id})).fetchone()
                if row is None:
                    return None
                cur = await conn.execute(
                    "SELECT id, household_id, name FROM people WHERE household_id = %s ORDER BY id", (household_id,))
                people = tuple(Person(*r) for r in await cur.fetchall())
        changed = [f for i, f in enumerate(_FIELDS) if row[1 + 2 * i] != row[2 + 2 * i]]
        logs.info(log, "people.household.changed", household=household_id, person=person_id, fields=len(changed),
                  changed=",".join(changed))
        return Household(household_id, row[0], edit.timezone, edit.profile, people, edit.locale, edit.unit_system,
                         edit.clock)
