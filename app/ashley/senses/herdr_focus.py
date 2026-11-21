"""Focus from a person's herdr bridges: the latest time they typed into any of their sessions on any machine
(`SessionList.last_typed_at`). A bridge that records none, or a person with no bridge, is no typing. A machine that
does not answer is skipped while another gave a time (a laptop that is off is not being typed on); when none gave one
and one failed, focus is unknown.

Logs `focus.unknown` (reason) for each bridge that cannot be read."""

import logging
from datetime import UTC, datetime

from .. import logs, services
from ..connections.connections import ConnectionsUnavailable
from ..herdr import machines
from ..herdr.bridge import Bridge
from ..herdr.model import BridgeFailed
from .focus import Focus, FocusUnavailable

log = logging.getLogger("ashley.senses")


class HerdrFocus(Focus):
    async def typed_at(self, household_id: int, person_id: int) -> datetime | None:
        try:
            held = await machines.held(household_id, person_id)
        except ConnectionsUnavailable as e:
            logs.warning(log, "focus.unknown", reason="connections_unavailable")
            raise FocusUnavailable("connections unavailable") from e
        latest: datetime | None = None
        failure: FocusUnavailable | None = None
        for machine in held:
            try:
                listed = await services.get(Bridge).sessions(machine.access)
                at = None if listed.last_typed_at is None else _parsed(listed.last_typed_at)
            except BridgeFailed as e:
                logs.warning(log, "focus.unknown", reason=e.reason)
                failure = failure or FocusUnavailable(e.reason)
                continue
            except FocusUnavailable as e:
                failure = failure or e
                continue
            latest = at if latest is None or (at is not None and at > latest) else latest
        if latest is None and failure is not None:
            raise failure
        return latest


def _parsed(text: str) -> datetime:
    """An ISO time from the bridge; one with no zone is UTC. Raises FocusUnavailable for one that is not a time."""
    try:
        at = datetime.fromisoformat(text)
    except ValueError as e:
        logs.warning(log, "focus.unknown", reason="bad_time")
        raise FocusUnavailable("bad_time") from e
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)
