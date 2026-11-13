"""The deployment's own secrets, which no outside service holds and no person edits: the key that signs file links
(`LINK_KEY`) and her Web Push identity (`VAPID`, the pair as one value so a race cannot split it). Each is one row of
`deployment_secrets`, sealed under the connections key as a connection's secret is, bound to its name.

Every pod settles them at start (`settle_one`): a row wins; with none, the env's value is written, and with no env value
either a fresh one is generated. The insert is `ON CONFLICT DO NOTHING` and is followed by reading the row back, so pods
on both sites starting at once all keep the one value that was written first. `DeploymentSecrets` is what a pod holds:
the env's values until the rows are settled, then the rows'."""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import AsyncConnection

from .. import logs
from ..db.database import Database
from ..services import Service
from .sealing import Sealer

log = logging.getLogger("ashley.connections")

LINK_KEY = "files_link_key"
VAPID = "vapid"

Outcome = Literal["found", "seeded", "generated", "none"]

_READ = "SELECT sealed FROM deployment_secrets WHERE name = %s"
_INSERT = "INSERT INTO deployment_secrets (name, sealed) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING"


def vapid_value(public_key: str, private_key: str) -> str:
    """The `VAPID` row's value for a pair, both base64url as `ashley.channels.push.config.Vapid` holds them."""
    return json.dumps({"public_key": public_key, "private_key": private_key}, sort_keys=True)


class DeploymentSecrets(Service):
    """The secrets in force on this pod. Built from the env's values; `settle` replaces them with the rows' once. The
    Null Object holds none and is settled already, so a process that never wires it waits for nothing."""

    def __init__(self, link_key: str = "", vapid_public_key: str = "", vapid_private_key: str = "") -> None:
        self._link_key = link_key
        self._vapid = (vapid_public_key, vapid_private_key)
        self._settled = asyncio.Event()

    @classmethod
    def null(cls) -> "DeploymentSecrets":
        made = cls()
        made.settle({})
        return made

    def link_key(self) -> str:
        """The key file links are signed with; empty when there is none."""
        return self._link_key

    def vapid_keys(self) -> tuple[str, str]:
        """Her VAPID public and private key, base64url; empty strings when there are none."""
        return self._vapid

    def settle(self, values: Mapping[str, str]) -> None:
        """Take the rows' values by name; a name missing from `values` keeps the env's. Wakes `settled`."""
        if LINK_KEY in values:
            self._link_key = values[LINK_KEY]
        if VAPID in values:
            pair = json.loads(values[VAPID])
            self._vapid = (str(pair["public_key"]), str(pair["private_key"]))
        self._settled.set()

    async def settled(self) -> None:
        """Returns once `settle` has run."""
        if not self._settled.is_set():
            await self._settled.wait()


@dataclass(frozen=True)
class Wanted:
    """One secret to settle: its name, the env's value (empty for none), and how to make a fresh one; `generate` None
    means none is made (the env names a value that is not usable, so nothing is written over its absence)."""

    name: str
    env: str
    generate: Callable[[], str] | None


async def settle_one(database: Database, sealer: Sealer, wanted: Wanted) -> tuple[str | None, Outcome]:
    """The value in force for `wanted` and how it came to be: `found` (a row was there, or another pod's write won),
    `seeded` (the env's was written), `generated`, or `none` (no row and nothing to write; the value is None).

    Raises `DatabaseUnavailable` or a psycopg error when the database cannot be read, and `Unsealable` when the row
    does not open under this key; a row is never written over. Logs `deployment_secret.settled` with the name and the
    outcome, never a value."""
    bound = f"deployment:{wanted.name}".encode()
    async with database.connection() as conn:
        value = await _read(conn, sealer, wanted.name, bound)
        outcome: Outcome = "found"
        if value is None:
            offered, outcome = (wanted.env, "seeded") if wanted.env else (
                (wanted.generate(), "generated") if wanted.generate is not None else (None, "none"))
            if offered is not None:
                await conn.execute(_INSERT, (wanted.name, sealer.seal(offered, bound)))
                value = await _read(conn, sealer, wanted.name, bound)
                outcome = outcome if value == offered else "found"
    logs.info(log, "deployment_secret.settled", name=wanted.name, outcome=outcome)
    return value, outcome


async def _read(conn: AsyncConnection[tuple[Any, ...]], sealer: Sealer, name: str, bound: bytes) -> str | None:
    cur = await conn.execute(_READ, (name,))
    row = await cur.fetchone()
    return None if row is None else sealer.open(bytes(row[0]), bound)
