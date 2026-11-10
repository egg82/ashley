"""OAuthConnections in Postgres, on the `connections` table `PostgresConnections` owns. Adding and replacing go through
it; renewal's reads and compare-and-set writes are here. The access token is sealed bound to its row, as the secret is."""

from .. import logs
from ..db.database import Database
from . import queries
from .connections import ConnectionsUnavailable
from .model import Connection, Grant, Holder, Kind, OAuthState, Opened
from .oauth_connections import OAuthConnections
from .postgres import PostgresConnections, connection_of, grant_args, log, translated
from .sealing import Sealer, Unsealable, bound_to


def _refresh_token(grant: Grant) -> str:
    if grant.refresh_token is None:
        raise ValueError("an OAuth connection is stored with the grant's refresh token")
    return grant.refresh_token


class PostgresOAuthConnections(OAuthConnections):
    def __init__(self, connections: PostgresConnections, database: Database, sealer: Sealer) -> None:
        self._connections = connections
        self._database = database
        self._sealer = sealer

    async def add_oauth(self, household_id: int, kind: Kind, label: str, base_url: str, grant: Grant,
                        added_by: int, holder: Holder | None = None) -> Connection:
        return await self._connections.add_granted(household_id, kind, label, base_url, _refresh_token(grant),
                                                   added_by, grant, holder)

    async def replace_oauth(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                            grant: Grant) -> Connection | None:
        return await self._connections.replace_granted(connection_id, household_id, person_id, base_url,
                                                       _refresh_token(grant), grant)

    async def state(self, connection_id: int, household_id: int, person_id: int | None = None) -> OAuthState | None:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(queries.OAUTH, {"id": connection_id, "household": household_id,
                                                         "person": person_id})
                row = await cur.fetchone()
        if row is None:
            return None
        connection = connection_of(row)
        bound = bound_to(household_id, connection.kind, connection.person_id)
        try:
            opened = Opened(connection, self._sealer.open(bytes(row[11]), bound))
            access = None if row[12] is None else self._sealer.open(bytes(row[12]), bound)
        except Unsealable as e:
            logs.error(log, "connections.unsealable", household=household_id, kind=connection.kind,
                       connection=connection.id)
            raise ConnectionsUnavailable("the stored secret does not open under this key") from e
        return OAuthState(opened, access, None if row[13] is None else float(row[13]), row[14])

    async def renewed(self, connection_id: int, version: int, grant: Grant) -> bool:
        with translated():
            async with self._database.connection() as conn:
                found = await (await conn.execute(queries.SEALED_FOR, {"id": connection_id})).fetchone()
                if found is None:
                    return False
                bound = bound_to(*found)
                args = {"id": connection_id, "version": version,
                        "secret": None if grant.refresh_token is None else self._sealer.seal(grant.refresh_token, bound),
                        **grant_args(self._sealer, grant, bound)}
                row = await (await conn.execute(queries.RENEWED, args)).fetchone()
        return row is not None

    async def needs_reconnect(self, connection_id: int, version: int) -> bool:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(queries.NEEDS_RECONNECT, {"id": connection_id, "version": version})
                row = await cur.fetchone()
        return row is not None
