"""A session piece's body (kind `session`, family `live`, format `session`): a reference to one of the bench owner's
Claude Code sessions, which the client shows as it runs (`api.claude_screen`). One JSON object of exactly `source`
(`herdr`, the owner's herdr bridge, the one source there is) and `session` (the Claude session id the bridge lists, 36
hex digits and dashes). The body names the session and nothing of what it shows: its screen is read from the bridge
each time it is shown and never stored."""

import json
import re
from dataclasses import dataclass
from typing import Literal

from .json_shape import object_of

Source = Literal["herdr"]
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass(frozen=True)
class SessionRef:
    source: Source
    session: str


def reference_of(body: str) -> SessionRef | None:
    """The session `body` names; None when it is empty or outside the shape above."""
    try:
        raw = object_of(json.loads(body))
    except ValueError:
        return None
    if raw is None or set(raw) != {"source", "session"} or raw["source"] != "herdr":
        return None
    session = raw["session"]
    if not isinstance(session, str) or SESSION_ID.fullmatch(session) is None:
        return None
    return SessionRef("herdr", session)


def well_formed(body: str) -> bool:
    """Whether `body` is empty (a draft) or a session reference of the shape above."""
    return not body.strip() or reference_of(body) is not None
