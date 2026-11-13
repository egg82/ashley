"""The env's `ESPHOME_NOISE_PSK` as the deployment's first household's satellites key (`key_kind`), written at each pod's
start where that household has none, so a deployment that ran on the env shows it in the connections room and keeps
reaching its satellites with no person step. Never over a row a person added or replaced; every pod on both sites may
run it at once, as `ashley.channels.discord.token_seed` does."""

import logging
from typing import Literal

from ... import logs
from ...connections.connections import Connections, ConnectionsUnavailable
from ...connections.kinds import FIRST_HOUSEHOLD
from .key_kind import API, NAME

log = logging.getLogger("ashley.channels.voice")

Outcome = Literal["seeded", "kept", "no_key", "unavailable"]


async def seed_key(connections: Connections, key: str) -> Outcome:
    """Seal `key` as `FIRST_HOUSEHOLD`'s satellites connection, with no adder and an empty label, unless that household
    already holds one. The key is not checked (it was in use).

    `seeded`; `kept` (a row was there, or there is no first household); `no_key` (no `CONNECTIONS_KEY`); `unavailable`
    (the database could not be reached or refused the row). Never raises; logs `voice.key_seed` with the outcome, never
    the key. Race-safe with no lease: `Connections.seed` is one insert that writes once, and the pods that lose see
    `kept`."""
    outcome: Outcome
    if not connections.can_open():
        outcome = "no_key"
    else:
        try:
            outcome = "kept" if await connections.seed(FIRST_HOUSEHOLD, NAME, API, key) is None else "seeded"
        except ConnectionsUnavailable:
            outcome = "unavailable"
    emit = logs.warning if outcome == "unavailable" else logs.info
    emit(log, "voice.key_seed", household=FIRST_HOUSEHOLD, outcome=outcome)
    return outcome
