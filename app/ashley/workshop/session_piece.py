"""A session piece's body (kind `session`, family `live`, format `session`): a reference to one of the bench owner's
Claude Code sessions, which the client shows as it runs (`api.claude_screen`). One JSON object of `source`
(`herdr`, the owner's herdr bridge, the one source there is), `session` (the Claude session id the bridge lists, 36
hex digits and dashes) and, optionally, `machine` (the label of the owner's herdr connection the session is on, 1 to
40 characters). A body with no `machine` is on the owner's default machine, the first made (`herdr.machines`). The body names the session and nothing of what it shows: its screen is read from the bridge
each time it is shown and never stored."""

import json
import re
from dataclasses import dataclass
from typing import Literal

from .json_shape import object_of

Source = Literal["herdr"]
MACHINE_MAX = 40
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass(frozen=True)
class SessionRef:
    source: Source
    session: str
    machine: str | None = None


def reference_of(body: str) -> SessionRef | None:
    """The session `body` names; None when it is empty or outside the shape above."""
    try:
        raw = object_of(json.loads(body))
    except ValueError:
        return None
    if raw is None or not {"source", "session"} <= set(raw) <= {"source", "session", "machine"} or raw["source"] != "herdr":
        return None
    session, machine = raw["session"], raw.get("machine")
    if not isinstance(session, str) or SESSION_ID.fullmatch(session) is None:
        return None
    if "machine" not in raw:
        return SessionRef("herdr", session)
    if not isinstance(machine, str) or not 1 <= len(machine) <= MACHINE_MAX:
        return None
    return SessionRef("herdr", session, machine)


def well_formed(body: str) -> bool:
    """Whether `body` is empty (a draft) or a session reference of the shape above."""
    return not body.strip() or reference_of(body) is not None
