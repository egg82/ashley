"""ConnectionResources in Postgres, table `connection_resources`. One transaction per call."""

from collections.abc import Mapping, Sequence

from .. import logs
from ..db.database import Database
from . import queries
from .model import Listed, Resource, ResourceKind
from .postgres import connection_of, log, translated
from .resources import ConnectionResources, HeldByHousehold, Usable, Use, permits

_RESOURCE = "r.ref, r.kind, r.name, r.shared"
_CONNECTION = ", ".join("c." + name for name in queries.COLUMNS.split(", "))
OF_HOUSEHOLD = (f"SELECT r.connection_id, {_RESOURCE} FROM connection_resources r JOIN connections c "
                f"ON c.id = r.connection_id WHERE c.household_id = %(household)s AND "
                "(c.person_id IS NULL OR c.person_id = %(person)s) ORDER BY r.connection_id, r.ref")
STORED = "SELECT ref, kind, name, shared FROM connection_resources WHERE connection_id = %(id)s ORDER BY ref"
OWNER = "SELECT person_id FROM connections WHERE id = %(id)s AND household_id = %(household)s FOR UPDATE"
UPSERT = ("INSERT INTO connection_resources (household_id, connection_id, ref, kind, name, shared) "
          "VALUES (%(household)s, %(id)s, %(ref)s, %(kind)s, %(name)s, %(shared)s) "
          "ON CONFLICT (connection_id, ref) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind")
DROP = "DELETE FROM connection_resources WHERE connection_id = %(id)s AND NOT (ref = ANY(%(refs)s::text[]))"
TARGET = (f"SELECT c.person_id, {_RESOURCE} FROM connections c JOIN connection_resources r ON r.connection_id = c.id "
          "WHERE c.id = %(id)s AND c.household_id = %(household)s AND (c.person_id IS NULL OR c.person_id = %(person)s) "
          "AND r.ref = %(ref)s FOR UPDATE OF c, r")
SHARE = ("UPDATE connection_resources SET shared = %(shared)s WHERE connection_id = %(id)s AND ref = %(ref)s "
         "RETURNING ref, kind, name, shared")
USABLE = (f"SELECT {_CONNECTION}, {_RESOURCE}, EXISTS (SELECT 1 FROM people WHERE id = %(speaker)s::bigint "
          "AND household_id = %(household)s) FROM connection_resources r JOIN connections c ON c.id = r.connection_id "
          "WHERE c.household_id = %(household)s AND r.kind = %(kind)s ORDER BY c.kind, c.label, c.id, r.ref")


def _resource(row: tuple[object, ...]) -> Resource:
    return Resource(str(row[0]), "mailbox", str(row[2]), bool(row[3]))


class PostgresConnectionResources(ConnectionResources):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def of_household(self, household_id: int, person_id: int | None = None) -> Mapping[int, tuple[Resource, ...]]:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(OF_HOUSEHOLD, {"household": household_id, "person": person_id})
                rows = await cur.fetchall()
        found: dict[int, list[Resource]] = {}
        for row in rows:
            found.setdefault(row[0], []).append(_resource(row[1:]))
        return {k: tuple(v) for k, v in found.items()}

    async def listed(self, connection_id: int, household_id: int, found: Sequence[Listed]) -> tuple[Resource, ...]:
        args = {"id": connection_id, "household": household_id}
        with translated():
            async with self._database.connection() as conn:
                owner = await (await conn.execute(OWNER, args)).fetchone()
                if owner is None:
                    return ()
                for one in found:
                    await conn.execute(UPSERT, {**args, "ref": one.ref, "kind": one.kind, "name": one.name,
                                                "shared": owner[0] is None})
                await conn.execute(DROP, {**args, "refs": [one.ref for one in found]})
                rows = await (await conn.execute(STORED, args)).fetchall()
        return tuple(_resource(r) for r in rows)

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str,
                    shared: bool) -> Resource | None:
        args = {"id": connection_id, "household": household_id, "person": person_id, "ref": ref, "shared": shared}
        with translated():
            async with self._database.connection() as conn:
                target = await (await conn.execute(TARGET, args)).fetchone()
                if target is None:
                    return None
                if target[0] is None and not shared:
                    raise HeldByHousehold
                row = await (await conn.execute(SHARE, args)).fetchone()
        if row is None:
            return None
        logs.info(log, "connections.resource_shared", household=household_id, connection=connection_id, shared=shared)
        return _resource(row)

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        args = {"household": use.household_id, "speaker": use.speaker_id, "kind": kind}
        with translated():
            async with self._database.connection() as conn:
                rows = await (await conn.execute(USABLE, args)).fetchall()
        found = [(connection_of(row[:11]), _resource(row[11:15]), bool(row[15])) for row in rows]
        return tuple(Usable(c, r) for c, r, member in found if permits(use, changing, c, r, member))

