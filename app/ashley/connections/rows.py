"""What every Postgres statement of the connections package shares: the translation of a database failure and a row made
into a `Connection` (columns as `queries.COLUMNS`)."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg

from .. import services
from ..db.database import DatabaseUnavailable
from .connections import ConnectionsUnavailable
from .kinds import ConnectionKinds
from .model import Connection


@contextmanager
def translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise ConnectionsUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise ConnectionsUnavailable("database unreachable") from e
    except psycopg.Error as e:
        raise ConnectionsUnavailable("the database refused it") from e


def connection_of(row: tuple[Any, ...]) -> Connection:
    if services.get(ConnectionKinds).get(row[2]) is None:
        raise ConnectionsUnavailable("a stored connection has an unknown kind")
    return Connection(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9],
                      tuple(row[10] or ()))
