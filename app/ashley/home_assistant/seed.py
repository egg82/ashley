"""The env's Home Assistant (`HA_URL`, `HA_TOKEN`) as household 1's `home_assistant` connection, written at start where
it has none (and tried again by `connected_homes.ConnectedHomes` until it is decided), so the house wired for the whole
process before keeps answering for its household with no person step. Never over a row a person added or replaced;
both sites may run it at once."""

import logging
from typing import Literal

from .. import logs
from ..connections import address
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD
from .homes import SCHEMES

log = logging.getLogger("ashley.home_assistant")
FALLBACK_HOUSEHOLD = FIRST_HOUSEHOLD
"""The household the env's HA belongs to: the first, whose house was wired for the whole process before."""

Outcome = Literal["seeded", "kept", "no_key", "bad_url", "unavailable"]


async def seed_from_env(connections: Connections, base_url: str, token: str,
                        household_id: int = FALLBACK_HOUSEHOLD) -> Outcome:
    """Seal `base_url` and `token` as the household's connection unless it has one. Never raises; logs `homes.seed` with
    the outcome: `seeded`, `kept` (it had one, or there is no such household), `no_key`, `bad_url`, `unavailable`
    (the database could not be reached or refused the row)."""
    base = address.base_url(base_url, SCHEMES)
    outcome: Outcome
    if not connections.can_open():
        outcome = "no_key"
    elif base is None:
        outcome = "bad_url"
    else:
        try:
            seeded = await connections.seed(household_id, "home_assistant", base, token)
            outcome = "kept" if seeded is None else "seeded"
        except ConnectionsUnavailable:
            outcome = "unavailable"
    emit = logs.warning if outcome in ("bad_url", "unavailable") else logs.info
    emit(log, "homes.seed", household=household_id, outcome=outcome)
    return outcome
