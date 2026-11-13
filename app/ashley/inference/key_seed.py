"""The env's provider keys as the deployment's first connections of their kinds: written at start where there are none,
so a deployment that ran on env keys shows them in the connections room and keeps every call on them with no person
step. Never over a row a person added or replaced; every pod on both sites may run it at once. The env's local
OpenAI-compatible server (`LOCAL_LLM_URL`) seeds the OpenAI-compatible connection labelled `local` the same way."""

import logging
from collections.abc import Iterable, Mapping
from typing import Literal

from .. import logs
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD
from . import compatible
from .keyed import KeyedProvider
from .provider_keys import KeyInForce

log = logging.getLogger("ashley.inference")

Outcome = Literal["seeded", "kept", "no_key", "unavailable", "bad_address"]


async def seed_from_env(connections: Connections, keyed: Iterable[KeyedProvider],
                        env: Mapping[str, str]) -> dict[str, Outcome]:
    """For each provider in `keyed` whose env key (`env`, by kind name) is non-empty, seal that key as
    `FIRST_HOUSEHOLD`'s connection of its kind, at the kind's fixed address with no adder and an empty label, unless
    that household already holds one of the kind. The key is not checked against the provider (it was in use).

    Returns each such kind's outcome, by kind name: `seeded`; `kept` (a row was there, or there is no first household);
    `no_key` (no `CONNECTIONS_KEY`); `unavailable` (the database could not be reached or refused the row). Kinds with
    no env key are not in the result. Never raises; logs `provider_keys.seed` per kind with the outcome, never the key.

    Race-safe with no lease: it rests on `Connections.seed`, one `INSERT ... WHERE NOT EXISTS ... ON CONFLICT DO
    NOTHING` against the unique index on household, kind, owner and label, so of several pods seeding at once exactly
    one row is written and the rest see `kept`."""
    outcomes: dict[str, Outcome] = {}
    for provider in keyed:
        key = env.get(provider.kind.name, "")
        if key:
            outcomes[provider.kind.name] = await _seeded(connections, provider, key)
    return outcomes


async def _seeded(connections: Connections, provider: KeyedProvider, key: str) -> Outcome:
    kind = provider.kind
    outcome: Outcome
    if not connections.can_open():
        outcome = "no_key"
    else:
        try:
            seeded = await connections.seed(FIRST_HOUSEHOLD, kind.name, provider.address, key)
            outcome = "kept" if seeded is None else "seeded"
        except ConnectionsUnavailable:
            outcome = "unavailable"
    emit = logs.warning if outcome == "unavailable" else logs.info
    emit(log, "provider_keys.seed", household=FIRST_HOUSEHOLD, kind=kind.name, outcome=outcome)
    return outcome


async def seed_compatible_from_env(connections: Connections, env: Mapping[str, KeyInForce]) -> dict[str, Outcome]:
    """For each OpenAI-compatible provider the env describes (`env`, label to key; empty when `LOCAL_LLM_URL` is
    unset), seal its key as `FIRST_HOUSEHOLD`'s connection of that kind under its label, at its address, with no adder
    and no catalogue provider (its calls stay unpriced), unless that household already holds one of the kind under
    that label. The key is not checked against the server (it was in use).

    Returns each label's outcome as `seed_from_env` does, plus `bad_address`: the address is not one the kind takes,
    so nothing is written and the env's server goes on answering. Never raises; logs `provider_keys.seed` per label
    with the kind and outcome, never the key or the address. Race-safe with no lease, as `seed_from_env` is."""
    outcomes: dict[str, Outcome] = {}
    for label, key in env.items():
        base = compatible.KIND.base_url(key.base_url)
        outcome: Outcome
        if base is None:
            outcome = "bad_address"
        elif not connections.can_open():
            outcome = "no_key"
        else:
            try:
                seeded = await connections.seed_labelled(FIRST_HOUSEHOLD, compatible.NAME, label, base, key.secret)
                outcome = "kept" if seeded is None else "seeded"
            except ConnectionsUnavailable:
                outcome = "unavailable"
        emit = logs.warning if outcome in ("unavailable", "bad_address") else logs.info
        emit(log, "provider_keys.seed", household=FIRST_HOUSEHOLD, kind=compatible.NAME, outcome=outcome)
        outcomes[label] = outcome
    return outcomes
