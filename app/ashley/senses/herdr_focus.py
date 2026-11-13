"""Focus from a person's herdr bridge: the latest time they typed into any of their sessions
(`SessionList.last_typed_at`). A bridge that records none, or a person with no bridge, is no typing.

Logs `focus.unknown` (reason) when it cannot be read; never when anyone typed."""

import logging
from datetime import UTC, datetime

from .. import logs, services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed
from .focus import Focus, FocusUnavailable

log = logging.getLogger("ashley.senses")


class HerdrFocus(Focus):
    async def typed_at(self, household_id: int, person_id: int) -> datetime | None:
        try:
            opened = await ports.opened(services.get(Connections), "herdr", household_id, person_id)
        except ConnectionsUnavailable as e:
            logs.warning(log, "focus.unknown", reason="connections_unavailable")
            raise FocusUnavailable("connections unavailable") from e
        if opened is None:
            return None
        try:
            listed = await services.get(Bridge).sessions(Access.of(opened.connection.base_url, opened.secret,
                                                                   person_id))
        except BridgeFailed as e:
            logs.warning(log, "focus.unknown", reason=e.reason)
            raise FocusUnavailable(e.reason) from e
        return None if listed.last_typed_at is None else _parsed(listed.last_typed_at)


def _parsed(text: str) -> datetime:
    """An ISO time from the bridge; one with no zone is UTC. Raises FocusUnavailable for one that is not a time."""
    try:
        at = datetime.fromisoformat(text)
    except ValueError as e:
        logs.warning(log, "focus.unknown", reason="bad_time")
        raise FocusUnavailable("bad_time") from e
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)
