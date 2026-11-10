"""The Watches service (`ashley.services`): the watches she keeps on reads that return something new (`decisions.md`,
"Watches wake her when what a read returns changes, until a condition or a time"). It records verdicts and keeps no
rules: the job judges, and the store stores what it is told, a wake together with the baseline it reports."""

from abc import abstractmethod

from ..services import Service
from .model import Arm, Armed, Check, Counts, Watch


class WatchesUnavailable(Exception):
    """The store could not be reached or written. Transient."""


class Watches(Service):
    @classmethod
    def null(cls) -> "Watches":
        return NullWatches()

    @abstractmethod
    async def arm(self, arm: Arm) -> Armed:
        """Store an `armed` watch. A live (armed or paused) watch of the same person, kind and target is updated
        instead: its `when`, `until`, `tools`, `interval_s`, `expires_at`, `brief`, `standing` and bench take the new
        values, its baseline,
        `version` and `series` are kept, and `armed_by` becomes `handoff` if either arming was one. Raises ValueError,
        before writing, for a `when` or `until` field outside `track`, a condition over its limits, `expires_at` not in
        the future, a malformed field, an unknown person, or a new watch past the person's `max_live`;
        WatchesUnavailable."""

    @abstractmethod
    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        """End that person's live watch on the target, reason `disarmed`. False, changing nothing, when there is
        none. Raises WatchesUnavailable."""

    @abstractmethod
    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        """The person's armed and paused watches, soonest expiry first. Raises WatchesUnavailable."""

    @abstractmethod
    async def get(self, watch_id: int) -> Watch | None:
        """One watch in any state. Raises WatchesUnavailable."""

    @abstractmethod
    async def due(self, limit: int) -> tuple[Watch, ...]:
        """At most `limit` live, unexpired watches whose `next_check_at` has come and that have no unsettled `wakes`
        row of their own, the longest due first. Raises WatchesUnavailable."""

    @abstractmethod
    async def record(self, watch_id: int, version: int, check: Check) -> bool:
        """Record one check, only while the watch is live at `version`; False, changing nothing, otherwise.
        `Baseline` stores the baseline, `version` + 1. Any check but `Failed` sets failures to 0 and arms a paused
        watch again. A successful read (`Baseline`, `Quiet`, `Woke`) moves a standing watch's `expires_at` to now plus the time it
        was armed for; `Failed` and `Later` do not. `Quiet` ends the watch `until` when `ends`. `Woke`, in one transaction, stores the baseline,
        `version` + 1, `series` + 1, `last_woke_at` and a `wakes` row of event id `watch:<id>:<new version>` (and
        ends it `until` when `ends`). `Later` records nothing but `next_check_at`, `retry_s` from now: no failure, no baseline, no state change. `Failed` adds a failure; at `fail_after` an armed watch becomes `paused` and a
        `paused` wake is stored in the same transaction. Every other outcome sets `next_check_at`: `interval_s` from now,
        or `retry_s` while paused. Raises WatchesUnavailable."""

    @abstractmethod
    async def expire(self, keep_s: float) -> Counts:
        """Live watches past `expires_at` end `expired`. Ended watches older than `keep_s` with no unsettled
        `wakes` row are deleted. Raises WatchesUnavailable."""


class NullWatches(Watches):
    """What an unwired process sees: every call raises, so nothing is armed or checked by mistake."""

    async def arm(self, arm: Arm) -> Armed:
        raise WatchesUnavailable("watches are not wired")

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise WatchesUnavailable("watches are not wired")

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        raise WatchesUnavailable("watches are not wired")

    async def get(self, watch_id: int) -> Watch | None:
        raise WatchesUnavailable("watches are not wired")

    async def due(self, limit: int) -> tuple[Watch, ...]:
        raise WatchesUnavailable("watches are not wired")

    async def record(self, watch_id: int, version: int, check: Check) -> bool:
        raise WatchesUnavailable("watches are not wired")

    async def expire(self, keep_s: float) -> Counts:
        raise WatchesUnavailable("watches are not wired")
