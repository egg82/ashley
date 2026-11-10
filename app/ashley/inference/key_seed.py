"""The env's provider keys as the deployment's first connections of their kinds: written at start where there are none,
so a deployment that ran on env keys shows them in the connections room and keeps every call on them with no person
step. Never over a row a person added or replaced; every pod on both sites may run it at once."""

from collections.abc import Iterable, Mapping
from typing import Literal

from ..connections.connections import Connections
from .keyed import KeyedProvider

Outcome = Literal["seeded", "kept", "no_key", "unavailable"]


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
    raise NotImplementedError
