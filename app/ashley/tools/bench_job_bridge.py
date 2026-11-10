"""The person's herdr bridge as a Claude Code job needs it: whether a job may start there (`ready`), and the access a
running job calls it with (`access_of`). `ready` raises `NotReady("herdr_unavailable")` for a bridge that does not
answer, which hands a Claude Code job off `waiting`. A bridge is ready when the person has connected one, it answers, reports the
`files` capability, and was set up with roots to start a session under."""

from typing import Literal

from .. import services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed

NotReadyReason = Literal["not_connected", "bridge_too_old", "no_roots", "herdr_unavailable", "bridge_refused",
                         "unavailable"]


class NotReady(Exception):
    def __init__(self, reason: NotReadyReason) -> None:
        super().__init__(reason)
        self.reason: NotReadyReason = reason


async def access_of(household_id: int, person_id: int) -> Access | None:
    """The access for the person's bridge, None when they have connected none. Raises ConnectionsUnavailable and
    BridgeFailed (`unexpected`) for an address that is not a bridge's."""
    opened = await ports.opened(services.get(Connections), "herdr", household_id, person_id)
    return None if opened is None else Access.of(opened.connection.base_url, opened.secret, person_id)


async def ready(household_id: int, person_id: int) -> Access:
    """The access for a bridge a job may start on. Raises NotReady."""
    try:
        access = await access_of(household_id, person_id)
    except ConnectionsUnavailable as e:
        raise NotReady("unavailable") from e
    except BridgeFailed as e:
        raise _not_ready(e) from e
    if access is None:
        raise NotReady("not_connected")
    try:
        who = await services.get(Bridge).whoami(access)
        if "files" not in who.capabilities:
            raise NotReady("bridge_too_old")
        listed = await services.get(Bridge).sessions(access)
    except BridgeFailed as e:
        raise _not_ready(e) from e
    if not listed.roots:
        raise NotReady("no_roots")
    return access


def _not_ready(e: BridgeFailed) -> NotReady:
    """A bridge that does not answer (`herdr_unavailable`) is one a job may wait for; any other refusal (a token, a
    person or a certificate it does not accept) is not."""
    return NotReady("herdr_unavailable" if e.reason == "herdr_unavailable" else "bridge_refused")
