"""ConnectPending in Postgres, table `connect_pending`. Every time is the database's own `now()`, so pods on two sites
agree on what has expired. The verifier is sealed bound to its household and person."""

import hashlib

from ..db.database import Database
from .connections import ConnectionsUnavailable
from .model import Holder
from .pending import ConnectPending, Pending
from .postgres import translated
from .sealing import Sealer, Unsealable


def _state(state: str) -> bytes:
    return hashlib.sha256(state.encode()).digest()


def _bound(household_id: int, person_id: int) -> bytes:
    return f"connect:{household_id}:{person_id}".encode()


class PostgresConnectPending(ConnectPending):
    def __init__(self, database: Database, sealer: Sealer, lifetime_minutes: int, most_in_flight: int) -> None:
        self._database = database
        self._sealer = sealer
        self._minutes = lifetime_minutes
        self._most = most_in_flight

    async def begin(self, state: str, pending: Pending) -> bool:
        sealed = self._sealer.seal(pending.verifier, _bound(pending.household_id, pending.person_id))
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("LOCK TABLE connect_pending IN SHARE ROW EXCLUSIVE MODE")
                await conn.execute("DELETE FROM connect_pending WHERE created_at < now() - make_interval(mins => %s)",
                                   (self._minutes,))
                cur = await conn.execute(
                    "INSERT INTO connect_pending (state_sha256, household_id, person_id, kind, label, holder, verifier) "
                    "SELECT %s, %s, %s, %s, %s, %s, %s WHERE (SELECT count(*) FROM connect_pending) < %s",
                    (_state(state), pending.household_id, pending.person_id, pending.kind, pending.label,
                     pending.holder, sealed, self._most))
                return cur.rowcount == 1

    async def take(self, state: str) -> Pending | None:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "DELETE FROM connect_pending WHERE state_sha256 = %s RETURNING household_id, person_id, kind, "
                    "label, holder, verifier, created_at >= now() - make_interval(mins => %s)",
                    (_state(state), self._minutes))
                row = await cur.fetchone()
        if row is None or not row[6]:
            return None
        try:
            verifier = self._sealer.open(bytes(row[5]), _bound(row[0], row[1]))
        except Unsealable as e:
            raise ConnectionsUnavailable("the stored verifier does not open under this key") from e
        holder: Holder = "household" if row[4] == "household" else "person"
        return Pending(row[0], row[1], row[2], row[3], holder, verifier)
