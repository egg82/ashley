"""The deployment's own secrets (`ashley.connections.deployment_secrets`) wired: `register` holds the env's values from
`wire` on, and `settle` (one of `ashley.wiring.warmups`) settles the rows at each pod's start, seeding them from
`FILES_LINK_KEY`, `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` or generating them, retried until the database answers."""

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable

import psycopg

from . import logs, services
from .channels.push.config import is_pair, new_pair
from .connections.deployment_secrets import LINK_KEY, VAPID, DeploymentSecrets, Wanted, settle_one, vapid_value
from .connections.sealing import VERSION as SEAL_VERSION, Sealer, Unsealable, key_from
from .db.database import Database, DatabaseUnavailable
from .settings import Settings

log = logging.getLogger("ashley.connections")

RETRY_S = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
"""The waits between attempts to settle, the last repeated."""


def register(settings: Settings) -> None:
    """Hold the env's values, in force until `settle` has read the rows."""
    services.register(DeploymentSecrets, DeploymentSecrets(settings.files_link_key, settings.vapid_public_key,
                                                           settings.vapid_private_key))


def new_link_key() -> str:
    """A fresh link key: 32 bytes from the system's CSPRNG, base64url (43 characters)."""
    return secrets.token_urlsafe(32)


def wanted(settings: Settings) -> list[Wanted]:
    """The link key, from the env or fresh; the VAPID pair, from the env when it names one usable pair, fresh when it
    names neither key, and neither seeded nor made when it names a pair that is not usable (logged `push.config_bad`,
    and push stays off until a person fixes the env, as before there was a row)."""
    pair = (settings.vapid_public_key, settings.vapid_private_key)
    if not any(pair):
        vapid = Wanted(VAPID, "", lambda: vapid_value(*new_pair()))
    elif is_pair(*pair):
        vapid = Wanted(VAPID, vapid_value(*pair), None)
    else:
        logs.warning(log, "push.config_bad", push="off")
        vapid = Wanted(VAPID, "", None)
    return [Wanted(LINK_KEY, settings.files_link_key, new_link_key), vapid]


async def settle(settings: Settings, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Settle every wanted secret and hand the values to `DeploymentSecrets`. Without `CONNECTIONS_KEY` nothing can be
    sealed, so the env's values stand. Each failure (the database away, a row this key cannot open) is logged
    `deployment_secrets.unsettled` and tried again after the next of `RETRY_S`; until then the env's values stand."""
    holder = services.get(DeploymentSecrets)
    if not settings.connections_key:
        logs.info(log, "deployment_secrets.unsealed", reason="no_key")
        holder.settle({})
        return
    sealer = Sealer({SEAL_VERSION: key_from(settings.connections_key)})
    pending = wanted(settings)
    values: dict[str, str] = {}
    attempt = 0
    while pending:
        try:
            value, _ = await settle_one(services.get(Database), sealer, pending[0])
        except (DatabaseUnavailable, psycopg.Error, Unsealable):
            logs.error(log, "deployment_secrets.unsettled", exc=True, name=pending[0].name, attempt=attempt)
            await sleep(RETRY_S[min(attempt, len(RETRY_S) - 1)])
            attempt += 1
            continue
        if value is not None:
            values[pending[0].name] = value
        pending.pop(0)
    holder.settle(values)
