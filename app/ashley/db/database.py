"""The database as a service (`ashley.services`): whether a writable primary can be reached, and a connection to it
for the systems that store their state there. Implementations live beside it; callers import only this interface."""

from abc import abstractmethod
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from ..services import Service


class DatabaseUnavailable(Exception):
    """No connection to the database could be had in time."""


@dataclass(frozen=True)
class Probe:
    """What one attempt to reach the database found. `writable` is meaningful only when `reachable`."""

    reachable: bool
    writable: bool


class Database(Service):
    @abstractmethod
    async def open(self) -> None:
        """Start the connection pool. Does not wait for the database: an unreachable one shows up in `probe`."""

    @abstractmethod
    async def close(self) -> None:
        """Release every connection."""

    @abstractmethod
    async def probe(self) -> Probe:
        """Try to open a connection and ask whether it is a writable primary. Never raises: a failure is
        `Probe(reachable=False, writable=False)` and a log line."""

    @abstractmethod
    def connection(self) -> AbstractAsyncContextManager[AsyncConnection[tuple[Any, ...]]]:
        """A pooled connection for the length of the `async with`, in a transaction committed when the block exits
        cleanly and rolled back when it raises. Raises DatabaseUnavailable on entering when none can be had in
        time. It lands on whichever member the connection string reaches; production's asks for a writable one."""

    @classmethod
    def null(cls) -> "Database":
        return NullDatabase()


class NullDatabase(Database):
    """Reaches nothing: what an unwired process sees."""

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def probe(self) -> Probe:
        return Probe(reachable=False, writable=False)

    def connection(self) -> AbstractAsyncContextManager[AsyncConnection[tuple[Any, ...]]]:
        raise DatabaseUnavailable("Database is not wired")
