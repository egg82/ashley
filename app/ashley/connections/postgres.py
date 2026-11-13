"""Connections in Postgres, table `connections`, each secret sealed by `sealing.Sealer` and bound to its household,
kind and owner. One transaction per call; the statements are in `queries`."""

import logging
from typing import Any

import psycopg

from .. import logs, services
from ..db.database import Database
from . import queries
from .connections import Connections, ConnectionsUnavailable, LabelTaken, TooMany
from .kinds import ConnectionKind, ConnectionKinds
from .model import Connection, Grant, Holder, Kind, Opened
from .moves import move
from .rows import connection_of, translated
from .sealing import Sealer, Unsealable, bound_to

log = logging.getLogger("ashley.connections")


def grant_args(sealer: Sealer, grant: Grant | None, bound: bytes) -> dict[str, Any]:
    """The statement arguments that store `grant`'s access token, sealed as the secret is, its expiry and its scopes;
    all empty for a pasted secret."""
    if grant is None:
        return {"access": None, "expires_in": None, "scopes": []}
    return {"access": sealer.seal(grant.access_token, bound), "expires_in": grant.expires_in_s,
            "scopes": list(grant.scopes)}


def _registered(kind: Kind) -> ConnectionKind:
    registered = services.get(ConnectionKinds).get(kind)
    if registered is None:
        raise ValueError("no such kind of connection")
    return registered


class PostgresConnections(Connections):
    def __init__(self, database: Database, sealer: Sealer) -> None:
        self._database = database
        self._sealer = sealer

    def can_open(self) -> bool:
        return True

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(queries.LIST, {"household": household_id, "person": person_id})
                rows = await cur.fetchall()
        return tuple(connection_of(r) for r in rows)

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(queries.OPEN, {"id": connection_id, "household": household_id,
                                                        "person": person_id})
                row = await cur.fetchone()
        if row is None:
            return None
        connection = connection_of(row)
        try:
            return Opened(connection, self._sealer.open(bytes(row[queries.WIDTH]), bound_to(household_id, connection.kind,
                                                                                 connection.person_id)))
        except Unsealable as e:
            logs.error(log, "connections.unsealable", household=household_id, kind=connection.kind,
                       connection=connection.id)
            raise ConnectionsUnavailable("the stored secret does not open under this key") from e

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        return await self.add_granted(household_id, kind, label, base_url, secret, added_by, None, holder)

    async def add_catalogued(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                             added_by: int, catalogue_provider: str | None) -> Connection:
        return await self.add_granted(household_id, kind, label, base_url, secret, added_by, None,
                                      catalogue_provider=catalogue_provider)

    async def add_granted(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str, added_by: int,
                          grant: Grant | None, holder: Holder | None = None,
                          catalogue_provider: str | None = None) -> Connection:
        """`add`, storing an OAuth `grant`'s access token, expiry and scopes beside `secret` (its refresh token), and the
        `catalogue_provider` as `add_catalogued` does."""
        registered = _registered(kind)
        holder = holder or registered.default_holder
        if holder not in registered.holders:
            raise ValueError("that kind cannot be held that way")
        owner = added_by if holder == "person" else None
        args: dict[str, Any] = {"household": household_id, "kind": kind, "label": label, "base_url": base_url, "person": added_by,
                "owner": owner, "most": registered.most, "catalogue_provider": catalogue_provider,
                "secret": self._sealer.seal(secret, bound_to(household_id, kind, owner)),
                **grant_args(self._sealer, grant, bound_to(household_id, kind, owner))}
        why: tuple[Any, ...] | None = None
        with translated():
            async with self._database.connection() as conn:
                await conn.execute(queries.LOCK, {"owner": f"{household_id}/{kind}/{owner}"})
                cur = await conn.execute(queries.ADD, args)
                row = await cur.fetchone()
                if row is None:
                    cur = await conn.execute(queries.WHY_NOT_ADDED, args)
                    why = await cur.fetchone()
        if row is None:
            if why is None or not why[0]:
                raise ValueError("added_by is not a person of that household")
            raise LabelTaken(kind) if why[1] else TooMany(kind)
        connection = connection_of(row)
        logs.info(log, "connections.added", household=household_id, kind=kind, connection=connection.id,
                  person=added_by)
        return connection

    async def move(self, connection_id: int, household_id: int, person_id: int, holder: Holder) -> Connection | None:
        moved = await move(self._database, self._sealer, connection_id, household_id, person_id, holder)
        if moved is not None:
            logs.info(log, "connections.moved", household=household_id, kind=moved.kind, connection=connection_id,
                      holder=holder)
        return moved

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        return await self.replace_granted(connection_id, household_id, person_id, base_url, secret, None)

    async def replace_catalogued(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                                 secret: str, catalogue_provider: str | None) -> Connection | None:
        return await self.replace_granted(connection_id, household_id, person_id, base_url, secret, None,
                                          catalogue_provider)

    async def replace_granted(self, connection_id: int, household_id: int, person_id: int, base_url: str, secret: str,
                              grant: Grant | None, catalogue_provider: str | None = None) -> Connection | None:
        """`replace`, storing an OAuth `grant` beside `secret` (its refresh token), and the `catalogue_provider` as
        `add_catalogued` does."""
        args: dict[str, Any] = {"id": connection_id, "household": household_id, "person": person_id,
                                "base_url": base_url, "catalogue_provider": catalogue_provider}
        with translated():
            async with self._database.connection() as conn:
                found = await (await conn.execute(queries.IDENTITY, args)).fetchone()
                if found is None:
                    return None
                bound = bound_to(household_id, found[0], found[1])
                args["secret"] = self._sealer.seal(secret, bound)
                args.update(grant_args(self._sealer, grant, bound))
                row = await (await conn.execute(queries.REPLACE, args)).fetchone()
        connection = None if row is None else connection_of(row)
        if connection is not None:
            logs.info(log, "connections.replaced", household=household_id, kind=connection.kind,
                      connection=connection.id, person=person_id)
        return connection

    async def relabel(self, connection_id: int, household_id: int, person_id: int, label: str) -> Connection | None:
        args = {"id": connection_id, "household": household_id, "person": person_id, "label": label}
        with translated():
            async with self._database.connection() as conn:
                found = await (await conn.execute(queries.IDENTITY, args)).fetchone()
                if found is None:
                    return None
                try:
                    row = await (await conn.execute(queries.RELABEL, args)).fetchone()
                except psycopg.errors.UniqueViolation as e:
                    raise LabelTaken(found[0]) from e
        connection = None if row is None else connection_of(row)
        if connection is not None:
            logs.info(log, "connections.relabeled", household=household_id, kind=connection.kind,
                      connection=connection.id, person=person_id)
        return connection

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        return await self.seed_labelled(household_id, kind, "", base_url, secret)

    async def seed_labelled(self, household_id: int, kind: Kind, label: str, base_url: str,
                            secret: str) -> Connection | None:
        sealed = self._sealer.seal(secret, bound_to(household_id, kind))
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(queries.SEED, {"household": household_id, "kind": kind, "label": label,
                                                        "base_url": base_url, "secret": sealed})
                row = await cur.fetchone()
        connection = None if row is None else connection_of(row)
        logs.info(log, "connections.seeded", household=household_id, kind=kind, seeded=connection is not None)
        return connection

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(queries.REMOVE, {"id": connection_id, "household": household_id,
                                                          "person": person_id})
                row = await cur.fetchone()
        if row is not None:
            logs.info(log, "connections.removed", household=household_id, kind=row[0], connection=connection_id)
        return row is not None

    async def answered(self, connection_id: int) -> None:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("UPDATE connections SET checked_at = now() WHERE id = %s", (connection_id,))
