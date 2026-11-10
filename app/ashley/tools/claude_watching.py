"""A session she handed work to is watched (`ashley.watches`): armed as a `claude_session` watch from the state it was in
and the bench whose talk handed it over, so its finishing wakes the turn that tells the person."""

import logging
from datetime import UTC, datetime, timedelta

from .. import logs, services
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed, Session
from ..watches.claude_session import NAME, items_of
from ..watches.config import CONFIG
from ..watches.model import Arm
from ..watches.watches import Watches, WatchesUnavailable

log = logging.getLogger("ashley.tools")


async def watching(household_id: int, person_id: int, bench_id: int | None, session: Session) -> bool:
    """Watch `session` from the state it is in, as a hand-off watch of the kind's defaults; False when that could not
    be recorded, which she tells the person."""
    kind = CONFIG.kinds[NAME]
    expires = datetime.now(UTC) + timedelta(hours=kind.handoff_hours)
    arm = Arm(household_id, person_id, NAME, session.id, session.label, bench_id, "handoff", kind.track, kind.when,
              kind.handoff_until, None, kind.interval_s, expires, items_of(session.id, session))
    try:
        await services.get(Watches).arm(arm)
    except (WatchesUnavailable, ValueError):
        logs.warning(log, "claude_code.unwatched", person=person_id)
        return False
    return True


async def state_of(access: Access, session_id: str) -> Session | None:
    """The session as the bridge lists it now, or None when it is not listed or the bridge cannot say."""
    try:
        listed = await services.get(Bridge).sessions(access)
    except BridgeFailed:
        return None
    return next((s for s in listed.sessions if s.id == session_id), None)
