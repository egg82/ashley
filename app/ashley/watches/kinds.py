"""The kinds of watch, a Type Object: a `Kind` reads the source for a group of watches, and the data in `watches.json`
holds each kind's defaults. A name no kind has gets the Null kind, so a stale row pauses instead of breaking the tick."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence

from ..criteria.record import Change
from .config import CONFIG
from .model import Read, ReadFailed, Watch


class Kind(ABC):
    name: str
    empty_is_absent = True
    """Whether a read of no items means the target is not there. A kind whose target is a container (a mailbox) says
    false: an empty one is still a valid target."""

    @property
    def outside(self) -> bool:
        """Whether what this kind reads can carry text written outside the household, so a turn it wakes starts
        tainted. A kind the data does not describe is outside."""
        found = CONFIG.kinds.get(self.name)
        return True if found is None else found.outside

    @abstractmethod
    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        """What each watch of `group` (one kind, one household, one person) reads now, by watch id. A failure is a
        `ReadFailed` with a reason slug, never an item missing. May raise, which fails the whole group."""

    def said(self, watch: Watch, changes: Sequence[Change]) -> str:
        """The wake as the page shows it, written from the watch's label and the tracked fields alone, never from
        anything the source displays."""
        return f"Watch {watch.label}: changed"

    def note(self, watch: Watch, changes: Sequence[Change]) -> str:
        """What only she reads with the turn: what the change means and what she may do about it."""
        return "A watch you keep changed. Say what changed from the message, and only if the person would want to know."

    async def detail(self, watch: Watch) -> str:
        """What only she reads beyond `note`, fetched when the wake's turn starts (a group's results); empty when the
        kind has none."""
        return ""

    async def available(self, household_id: int, person_id: int) -> bool:
        """Whether this person has connected the source the kind reads, so she may offer to watch it. May raise
        what the connections raise."""
        return False

    async def label(self, watch: Watch) -> str:
        """What a person calls the watch's target; the target itself when the kind cannot say."""
        return watch.target

    async def hold(self, nudge: Callable[[], None]) -> None:
        """Run by the job for as long as it runs, so only under its lease: a kind told of changes by its source, not
        polling it, holds its connections here and calls `nudge` when a read may now return something new, which checks
        the due watches at once. Returns at once for a kind that polls. Never raises but CancelledError."""
        return None


class NullKind(Kind):
    """The kind of a name nothing implements: every read fails `unknown_kind`."""

    name = "null"

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        return {w.id: ReadFailed("unknown_kind") for w in group}


class Registry:
    """The kinds by name; `get` answers the Null kind for a name it lacks."""

    def __init__(self, kinds: Sequence[Kind]) -> None:
        self._kinds = {k.name: k for k in kinds}

    def get(self, name: str) -> Kind:
        return self._kinds.get(name, NullKind())

    def all(self) -> tuple[Kind, ...]:
        return tuple(self._kinds.values())
