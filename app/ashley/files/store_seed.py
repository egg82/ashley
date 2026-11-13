"""The env's `FILES_ENDPOINTS`, `FILES_BUCKET`, `FILES_ACCESS_KEY` and `FILES_SECRET_KEY` as the deployment's first
object store connection, written at each pod's start where there is none, so a deployment that ran on the env shows it
in the connections room and keeps its files with no person step. Never over a row a person added or replaced; every pod
on both sites may run it at once, as `ashley.inference.key_seed` does."""

import logging
from typing import Literal

from .. import logs
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD
from .store_kind import KIND, NAME, Keys

log = logging.getLogger("ashley.files")

Outcome = Literal["seeded", "kept", "no_key", "unavailable", "bad_address"]


async def seed_store(connections: Connections, keys: Keys) -> Outcome:
    """Seal `keys` as `FIRST_HOUSEHOLD`'s object store connection, with no adder and an empty label, unless that
    household already holds one. The store is not checked (it was in use).

    `seeded`; `kept` (a row was there, or there is no first household); `no_key` (no `CONNECTIONS_KEY`); `unavailable`
    (the database could not be reached or refused the row); `bad_address` (the endpoints are not ones the kind takes,
    so nothing is written and the env's store goes on answering). Never raises; logs `files.store_seed` with the
    outcome, never an address or key. Race-safe with no lease: `Connections.seed` is one insert that writes once, and
    the pods that lose see `kept`."""
    base = KIND.base_url(keys.endpoints)
    outcome: Outcome
    if base is None:
        outcome = "bad_address"
    elif not connections.can_open():
        outcome = "no_key"
    else:
        try:
            outcome = "kept" if await connections.seed(FIRST_HOUSEHOLD, NAME, base, keys.secret()) is None else "seeded"
        except ConnectionsUnavailable:
            outcome = "unavailable"
    emit = logs.warning if outcome in ("unavailable", "bad_address") else logs.info
    emit(log, "files.store_seed", household=FIRST_HOUSEHOLD, outcome=outcome)
    return outcome
