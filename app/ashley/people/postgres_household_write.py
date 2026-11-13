"""A household's own fields written in Postgres: one UPDATE that answers both the old and new row, so the log line names
what changed without a second read racing another write."""

import logging
from dataclasses import fields

from .. import logs
from ..db.database import Database
from .household_write import HouseholdWriter
from .model import Household, HouseholdEdit, QuietHours
from .postgres import QUIET_COLUMNS, person_of, translated

log = logging.getLogger("ashley.people")
_FIELDS = tuple(f.name for f in fields(HouseholdEdit))
_PUT = (
    "UPDATE households SET timezone = %(timezone)s, profile = %(profile)s, locale = %(locale)s, "
    "unit_system = %(unit_system)s, clock = %(clock)s, latitude = %(latitude)s, longitude = %(longitude)s "
    "WHERE id = %(id)s "
    "RETURNING new.name, old.timezone, new.timezone, old.profile, new.profile, old.locale, new.locale, "
    "old.unit_system, new.unit_system, old.clock, new.clock, old.latitude, new.latitude, old.longitude, new.longitude"
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
                    f"SELECT p.id, p.household_id, p.name, false, {QUIET_COLUMNS} FROM people p WHERE p.household_id = %s "
                    "ORDER BY p.id", (household_id,))
                people = tuple(person_of(r) for r in await cur.fetchall())
        changed = [f for i, f in enumerate(_FIELDS) if row[1 + 2 * i] != row[2 + 2 * i]]
        logs.info(log, "people.household.changed", household=household_id, person=person_id, fields=len(changed),
                  changed=",".join(changed))
        return Household(household_id, row[0], edit.timezone, edit.profile, people, edit.locale, edit.unit_system,
                         edit.clock, edit.latitude, edit.longitude)

    async def put_quiet(self, household_id: int, person_id: int, quiet: QuietHours | None) -> bool:
        window = (None, None, None) if quiet is None else (quiet.start, quiet.end, quiet.timezone)
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "UPDATE people SET quiet_from = %s, quiet_to = %s, quiet_timezone = %s "
                    "WHERE id = %s AND household_id = %s", (*window, person_id, household_id))
                found = cur.rowcount == 1
        if found:
            logs.info(log, "people.quiet.changed", household=household_id, person=person_id, set=quiet is not None)
        return found
