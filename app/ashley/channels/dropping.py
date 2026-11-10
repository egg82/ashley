"""The work of a turn deleted with no turn of hers (`channels.inflight`); logged `respond.work_undropped` when it could not
be deleted."""

import logging

from .. import logs, services
from ..conversations.inflight import Claim, InFlight, InFlightError, Leaving

log = logging.getLogger("ashley.channels")


async def dropped(claim: Claim, leaving: Leaving | None = None) -> bool:
    """The work of `claim` deleted with no turn of hers (leaving what `leaving` says, `InFlight.drop_leaving`), and
    whether no work for the turn remains; logged when it could not be deleted. Never raises."""
    inflight = services.get(InFlight)
    try:
        gone = await (inflight.drop(claim) if leaving is None else inflight.drop_leaving(claim, leaving))
    except InFlightError:
        gone = False
    if not gone:
        logs.warning(log, "respond.work_undropped", said=claim.said_id)
    return gone
