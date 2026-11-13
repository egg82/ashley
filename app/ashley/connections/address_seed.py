"""The env's addresses for services that need no key (`WYOMING_STT_URL`, `SEARXNG_URL`) as the deployment's first
connections of their kinds, written at each pod's start where there are none, so a deployment that ran on the env shows
them in the connections room and keeps answering with no person step. Never over a row a person added or replaced;
every pod on both sites may run it at once, as `ashley.inference.key_seed` does."""

import logging
from collections.abc import Iterable
from typing import Literal

from .. import logs
from .connections import Connections, ConnectionsUnavailable
from .kinds import FIRST_HOUSEHOLD, ConnectionKind

log = logging.getLogger("ashley.connections")

NO_SECRET = "none"
"""The secret stored for a kind that takes none, as a local OpenAI-compatible server's is when `LOCAL_LLM_API_KEY` is unset."""

Outcome = Literal["seeded", "kept", "no_key", "unavailable", "bad_address"]


async def seed_addresses(connections: Connections, wanted: Iterable[tuple[ConnectionKind, str]]) -> dict[str, Outcome]:
    """For each kind in `wanted` whose env address is non-empty, seal it as `FIRST_HOUSEHOLD`'s connection of that kind,
    with no adder and an empty label, unless that household already holds one. The address is not checked against the
    service (it was in use).

    Returns each such kind's outcome by kind name: `seeded`; `kept` (a row was there, or there is no first household);
    `no_key` (no `CONNECTIONS_KEY`); `unavailable` (the database could not be reached or refused the row);
    `bad_address` (not one the kind takes, so nothing is written and the env's address goes on answering). Never raises;
    logs `connections.address_seed` per kind with the outcome, never the address. Race-safe with no lease:
    `Connections.seed` is one insert that writes once, and the pods that lose see `kept`."""
    outcomes: dict[str, Outcome] = {}
    for kind, env in wanted:
        if not env:
            continue
        base = kind.base_url(env)
        outcome: Outcome
        if base is None:
            outcome = "bad_address"
        elif not connections.can_open():
            outcome = "no_key"
        else:
            try:
                outcome = "kept" if await connections.seed(FIRST_HOUSEHOLD, kind.name, base, NO_SECRET) is None else "seeded"
            except ConnectionsUnavailable:
                outcome = "unavailable"
        emit = logs.warning if outcome in ("unavailable", "bad_address") else logs.info
        emit(log, "connections.address_seed", household=FIRST_HOUSEHOLD, kind=kind.name, outcome=outcome)
        outcomes[kind.name] = outcome
    return outcomes
