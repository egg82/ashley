"""What the database raises, as what the service promises."""

from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import errors

from ..db.database import DatabaseUnavailable
from .conversations import ConversationsUnavailable, UnknownHousehold, UnknownPerson

READ_ONLY_TRANSACTION = "25006"

_FOREIGN_KEYS: dict[str, type[Exception]] = {
    "conversations_household_id_fkey": UnknownHousehold,
    "conversation_participants_person_id_household_id_fkey": UnknownPerson,
    "turns_speaker_id_household_id_fkey": UnknownPerson,
}


@contextmanager
def translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise ConversationsUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise ConversationsUnavailable("database unreachable") from e
    except errors.ForeignKeyViolation as e:
        known = _FOREIGN_KEYS.get(e.diag.constraint_name or "")
        if known is None:
            raise
        raise known(e.diag.constraint_name) from e
    except psycopg.Error as e:
        if e.sqlstate == READ_ONLY_TRANSACTION:
            raise ConversationsUnavailable("database is not writable") from e
        raise
