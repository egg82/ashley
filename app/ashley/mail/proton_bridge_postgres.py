"""ProtonBridge in Postgres, tables `proton_bridge` and `proton_bridge_accounts`. The vault and keychain are sealed under
the connections key as connection secrets are, bound to what they are, so one does not open as the other. One
transaction per call; the statements are in `proton_bridge_queries`."""

import base64
import hashlib
import hmac
import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, LiteralString

import psycopg

from .. import logs
from ..connections.sealing import Sealer, Unsealable
from ..db.database import Database, DatabaseUnavailable
from . import proton_bridge_queries as q
from .proton_bridge import (Account, AccountState, Auth, BridgeUnavailable, Holder, KeeperAccess, ProtonBridge, Sync,
                            Vault)

log = logging.getLogger("ashley.mail")
VAULT_BOUND = b"proton_bridge:vault"
KEYCHAIN_BOUND = b"proton_bridge:keychain"
KEEPER_BOUND = b"proton_bridge:keeper"


@contextmanager
def translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise BridgeUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise BridgeUnavailable("database unreachable") from e
    except psycopg.Error as e:
        raise BridgeUnavailable("the database refused it") from e


def token_sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _account(row: tuple[Any, ...]) -> Account:
    return Account(row[0], row[1], row[2], row[3], tuple(row[4]), row[5], row[6], row[7])


class PostgresProtonBridge(ProtonBridge):
    def __init__(self, database: Database, sealer: Sealer) -> None:
        self._database = database
        self._sealer = sealer

    async def _one(self, statement: LiteralString, args: dict[str, Any]) -> tuple[Any, ...] | None:
        with translated():
            async with self._database.connection() as conn:
                return await (await conn.execute(statement, args)).fetchone()

    async def holder(self) -> Holder:
        row = await self._one(q.HOLDER, {})
        assert row is not None
        return Holder(row[0], row[1], row[2], None if row[3] is None else float(row[3]), row[4])

    async def raise_epoch(self, expected: int, site: str, token_sha256: bytes,
                          access: KeeperAccess | None = None) -> int | None:
        sealed = None if access is None else self._sealer.seal(
            json.dumps({"token": access.token, "certificate": access.certificate}), KEEPER_BOUND)
        row = await self._one(q.RAISE, {"expected": expected, "site": site, "token": token_sha256, "access": sealed})
        return None if row is None else int(row[0])

    async def keeper_access(self, epoch: int) -> KeeperAccess | None:
        row = await self._one(q.KEEPER_ACCESS, {"epoch": epoch})
        if row is None or row[0] is None:
            return None
        try:
            opened = json.loads(self._sealer.open(bytes(row[0]), KEEPER_BOUND))
        except Unsealable as e:
            logs.error(log, "proton_bridge.unsealable", what="keeper_access")
            raise BridgeUnavailable("the stored keeper access does not open under this key") from e
        return KeeperAccess(opened["token"], opened["certificate"])

    async def pod_started(self, epoch: int, pod: str) -> bool:
        return await self._one(q.POD_STARTED, {"epoch": epoch, "pod": pod}) is not None

    async def authorize(self, epoch: int, token: str) -> Auth:
        row = await self._one(q.AUTH, {})
        assert row is not None
        if row[0] != epoch:
            return "stale_epoch"
        known = None if row[1] is None else bytes(row[1])
        return "ok" if known is not None and hmac.compare_digest(known, token_sha256(token)) else "bad_token"

    async def heartbeat(self, epoch: int, certificate_sha256: str | None) -> bool:
        return await self._one(q.HEARTBEAT, {"epoch": epoch, "certificate": certificate_sha256}) is not None

    async def vault(self, epoch: int) -> Vault | None:
        row = await self._one(q.VAULT, {"epoch": epoch})
        if row is None:
            return None
        try:
            return Vault(row[0], self._open(row[1], VAULT_BOUND), self._open(row[2], KEYCHAIN_BOUND))
        except Unsealable as e:
            logs.error(log, "proton_bridge.unsealable", generation=row[0])
            raise BridgeUnavailable("the stored vault does not open under this key") from e

    async def write_back(self, epoch: int, generation: int, vault: bytes, keychain: bytes) -> int | None:
        row = await self._one(q.WRITE_BACK, {"epoch": epoch, "generation": generation,
                                             "vault": self._seal(vault, VAULT_BOUND),
                                             "keychain": self._seal(keychain, KEYCHAIN_BOUND)})
        return None if row is None else int(row[0])

    async def accounts(self) -> tuple[Account, ...]:
        with translated():
            async with self._database.connection() as conn:
                rows = await (await conn.execute(q.ACCOUNTS, {"user": None})).fetchall()
        return tuple(_account(r) for r in rows)

    async def add_account(self, connection_id: int, proton_user_id: str, addresses: tuple[str, ...],
                          synced_epoch: int = 0) -> Account:
        args = {"connection": connection_id, "user": proton_user_id, "addresses": list(addresses),
                "synced": synced_epoch}
        with translated():
            async with self._database.connection() as conn:
                await conn.execute(q.ADD_ACCOUNT, args)
                await conn.execute(q.CLEAR_LOGIN, args)
                row = await (await conn.execute(q.ACCOUNTS, args)).fetchone()
        assert row is not None
        return _account(row)

    async def set_state(self, epoch: int, proton_user_id: str, state: AccountState) -> int | None:
        args = {"epoch": epoch, "user": proton_user_id, "state": state}
        with translated():
            async with self._database.connection() as conn:
                row = await (await conn.execute(q.SET_STATE, args)).fetchone()
                if row is not None and state != "locked":
                    await conn.execute(q.NEEDS_LOGIN if state == "signed_out" else q.CLEAR_LOGIN,
                                       {"connection": row[1]})
        return None if row is None else int(row[0])

    async def sync(self, epoch: int, proton_user_id: str, event: Sync, progress: float | None = None) -> int | None:
        row = await self._one(q.SYNC[event], {"epoch": epoch, "user": proton_user_id, "progress": progress})
        return None if row is None else int(row[0])

    def _seal(self, blob: bytes, bound: bytes) -> bytes:
        return self._sealer.seal(base64.b64encode(blob).decode(), bound)

    def _open(self, sealed: bytes | None, bound: bytes) -> bytes | None:
        return None if sealed is None else base64.b64decode(self._sealer.open(bytes(sealed), bound))
