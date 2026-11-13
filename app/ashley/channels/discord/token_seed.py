"""The env's `DISCORD_BOT_TOKEN` as the deployment's first Discord connection, written at each pod's start where there is
none, so a deployment that ran on the env shows it in the connections room and keeps answering with no person step.
Never over a row a person added or replaced; every pod on both sites may run it at once, as `ashley.inference.key_seed`
does."""

import logging
from typing import Literal

from ... import logs
from ...connections.connections import Connections, ConnectionsUnavailable
from ...connections.kinds import FIRST_HOUSEHOLD
from .token_kind import API, NAME

log = logging.getLogger("ashley.channels.discord")

Outcome = Literal["seeded", "kept", "no_key", "unavailable"]


async def seed_token(connections: Connections, token: str) -> Outcome:
    """Seal `token` as `FIRST_HOUSEHOLD`'s Discord connection, with no adder and an empty label, unless that household
    already holds one. The token is not checked against Discord (it was in use).

    `seeded`; `kept` (a row was there, or there is no first household); `no_key` (no `CONNECTIONS_KEY`); `unavailable`
    (the database could not be reached or refused the row). Never raises; logs `discord.token_seed` with the outcome,
    never the token. Race-safe with no lease: `Connections.seed` is one insert that writes once, and the pods that lose
    see `kept`."""
    outcome: Outcome
    if not connections.can_open():
        outcome = "no_key"
    else:
        try:
            outcome = "kept" if await connections.seed(FIRST_HOUSEHOLD, NAME, API, token) is None else "seeded"
        except ConnectionsUnavailable:
            outcome = "unavailable"
    emit = logs.warning if outcome == "unavailable" else logs.info
    emit(log, "discord.token_seed", household=FIRST_HOUSEHOLD, outcome=outcome)
    return outcome
