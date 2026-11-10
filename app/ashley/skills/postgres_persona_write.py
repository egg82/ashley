"""The PersonaWriter service in Postgres (`persona_rows`). A change locks its household's section for the transaction."""

import logging
from collections.abc import Mapping

from .. import logs
from ..db.database import Database
from ..text import has_nul
from . import persona_rows as rows
from .config import SkillsConfig
from .persona_write import PersonaRefused, PersonaWriter
from .postgres_persona import translated

log = logging.getLogger("ashley.skills")


def _fits(text: str, limit: int) -> bool:
    return bool(text.strip()) and len(text) <= limit and not has_nul(text)


class PostgresPersonaWriter(PersonaWriter):
    def __init__(self, database: Database, config: SkillsConfig, shipped: Mapping[str, str]) -> None:
        """`shipped` is every `allowed` section's id and shipped body (`persona.sections.catalogue`)."""
        self._database = database
        self._config = config
        self._shipped = shipped

    def _check(self, section: str, why: str) -> None:
        if section not in self._shipped:
            raise PersonaRefused("locked")
        if not _fits(why, self._config.max_note_chars):
            raise PersonaRefused("bad_note")

    async def edit(self, household_id: int, section: str, body: str, why: str, base_version: int,
                   person_id: int) -> int:
        self._check(section, why)
        if not _fits(body, self._config.max_body_chars):
            raise PersonaRefused("bad_body")
        return await self._write(household_id, section, base_version, person_id, body, "Changed", why, None)

    async def revert(self, household_id: int, section: str, to_version: int, why: str, base_version: int,
                     person_id: int) -> int:
        self._check(section, why)
        what = "Back to the shipped text" if to_version == 0 else f"Brought back version {to_version}"
        return await self._write(household_id, section, base_version, person_id, None, what, why, to_version)

    async def _write(self, household_id: int, section: str, base_version: int, person_id: int, body: str | None,
                     what: str, why: str, restored_from: int | None) -> int:
        """The next version, with `body`, or with `restored_from`'s body when that is set."""
        with translated():
            async with self._database.connection() as conn:
                await rows.lock(conn, household_id, section)
                head = await rows.head(conn, household_id, section)
                newest = 0 if head is None else head.version
                if base_version != newest:
                    raise PersonaRefused("stale")
                if restored_from:
                    body = await self._restorable(conn, household_id, section, restored_from)
                if self._text(body, section) == self._text(None if head is None else head.body, section):
                    raise PersonaRefused("unchanged")
                await rows.insert(conn, household_id, section, newest + 1, body, what, why, base_version,
                                  restored_from, person_id)
        logs.info(log, "persona.changed", household=household_id, person=person_id, section=section,
                  version=newest + 1, change="edit" if restored_from is None else "revert",
                  chars=0 if body is None else len(body))
        return newest + 1

    async def _restorable(self, conn: rows.Conn, household_id: int, section: str, version: int) -> str:
        found, body = await rows.body_of(conn, household_id, section, version)
        if not found or body is None:
            raise PersonaRefused("no_such_version")
        return body

    def _text(self, body: str | None, section: str) -> str:
        """The section's text in force with `body` as its override."""
        return (self._shipped[section] if body is None else body).strip()
