"""The PersonaOverrides service in Postgres (`persona_rows`)."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager

import psycopg

from ..db.database import Database, DatabaseUnavailable
from . import persona_rows as rows
from .config import SkillsConfig
from .persona import PersonaOverrides, PersonaUnavailable, PersonaVersion

READ_ONLY_TRANSACTION = "25006"


@contextmanager
def translated() -> Generator[None]:
    """The database's failures as PersonaUnavailable."""
    try:
        yield
    except DatabaseUnavailable as e:
        raise PersonaUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise PersonaUnavailable("database unreachable") from e
    except psycopg.Error as e:
        if e.sqlstate == READ_ONLY_TRANSACTION:
            raise PersonaUnavailable("database is not writable") from e
        raise


class PostgresPersonaOverrides(PersonaOverrides):
    def __init__(self, database: Database, config: SkillsConfig) -> None:
        self._database = database
        self._config = config

    async def heads(self, household_id: int) -> Mapping[str, PersonaVersion]:
        with translated():
            async with self._database.connection() as conn:
                return await rows.heads(conn, household_id)

    async def changelog(self, household_id: int, section: str) -> tuple[PersonaVersion, ...]:
        with translated():
            async with self._database.connection() as conn:
                return await rows.changelog(conn, household_id, section, self._config.changelog_read)
