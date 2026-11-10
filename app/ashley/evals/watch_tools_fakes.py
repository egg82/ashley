"""What the watch-tools eval stands in for: one person's herdr bridge with a fixed set of Claude Code sessions. The
bridge lists them and shows a screen; every other call fails as an unreachable bridge, so nothing acts on a machine."""

from datetime import UTC, datetime

from ..connections.connections import NullConnections
from ..connections.model import Connection, Opened
from ..herdr.bridge import NullBridge
from ..herdr.model import Access, Screen, Session, SessionList

SESSIONS = (
    Session("7f3a9c10-2b1e", "ashley-wiring", "/home/eval/ashley", "working", 12, None),
    Session("c4d8e215-9a60", "k8s-upgrade", "/home/eval/kubernetes", "working", 31, None),
    Session("e5f6a7b8-1d42", "docs-pass", "/home/eval/docs", "idle", 5, None))
PIN = "0" * 64
BASE = f"https://bridge.eval:7843#sha256={PIN}"
_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


class EvalBridge(NullBridge):
    async def sessions(self, access: Access) -> SessionList:
        return SessionList(SESSIONS, None, ("/home/eval",))

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        return Screen("working...", False, 1)


class EvalConnections(NullConnections):
    """`person_id` has a herdr bridge in `household_id`; nothing else is connected."""

    def __init__(self, household_id: int, person_id: int) -> None:
        self._one = Connection(1, household_id, "herdr", BASE, person_id, _WHEN, _WHEN, person_id)

    def can_open(self) -> bool:
        return True

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        mine = household_id == self._one.household_id and person_id == self._one.person_id
        return (self._one,) if mine else ()

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        mine = (connection_id, household_id, person_id) == (self._one.id, self._one.household_id, self._one.person_id)
        return Opened(self._one, "eval-token") if mine else None


def id_of(label: str) -> str:
    """The id of the session labelled `label`."""
    return next(s.id for s in SESSIONS if s.label == label)
