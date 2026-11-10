"""What the Watches store takes and hands out: a watch, the request that arms one, and the five checks `record` takes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..criteria.condition import Condition
from ..criteria.record import Change
from .diff import Items

ArmedBy = Literal["ashley", "handoff"]
State = Literal["armed", "paused", "ended"]
FailReason = Literal["unreachable", "not_connected", "refused", "bad_result", "too_many_items", "unknown_kind"]
EndReason = Literal["until", "expired", "disarmed"]
MAX_BRIEF = 500


@dataclass(frozen=True)
class Arm:
    """A request to watch `target` of `kind` for `person_id`, shown as `label`, armed on `bench_id`'s talk (or None).
    `track` names the tracked fields; `when` and `until` read only those. `tools` are the names its turn may use
    (None: only the ones that read). `expires_at` is aware. `baseline`, when given, is what the target is in now.
    `brief` is what its turn is for, people's data and never logged. A `standing` watch's `expires_at` moves forward by
    the time it was armed for on every successful read. `taint` is what tainted the turn that armed it, None for an untainted
    one: the woken turn starts `inherited` (`Watch.taint`). `made_in` is the conversation and turn that armed it when
    `taint` is set, None for a watch armed before it was kept."""

    household_id: int
    person_id: int
    kind: str
    target: str
    label: str
    bench_id: int | None
    armed_by: ArmedBy
    track: tuple[str, ...]
    when: Condition
    until: Condition | None
    tools: tuple[str, ...] | None
    interval_s: float
    expires_at: datetime
    baseline: Items | None = None
    brief: str | None = None
    standing: bool = False
    taint: str | None = None
    made_in: tuple[int, int] | None = None


@dataclass(frozen=True)
class Armed:
    """The watch `arm` stored: `new` is False when it updated a live watch of the same person, kind and target."""

    id: int
    new: bool


@dataclass(frozen=True)
class Watch:
    """One watch. `reason` is None while armed; for a paused watch the failure slug, for an ended one its
    `EndReason`. `baseline` is None until the first check; `version` rises each time a baseline is stored and `series`
    each time the watch wakes her. `brief`, `standing`, `taint` and `made_in` are as `Arm` has them."""

    id: int
    household_id: int
    person_id: int
    kind: str
    target: str
    label: str
    bench_id: int | None
    armed_by: ArmedBy
    track: tuple[str, ...]
    when: Condition
    until: Condition | None
    tools: tuple[str, ...] | None
    interval_s: float
    expires_at: datetime
    state: State
    reason: str | None
    failures: int
    version: int
    series: int
    baseline: Items | None
    next_check_at: datetime
    armed_at: datetime
    last_woke_at: datetime | None
    ended_at: datetime | None
    brief: str | None = None
    standing: bool = False
    taint: str | None = None
    made_in: tuple[int, int] | None = None


@dataclass(frozen=True)
class Baseline:
    """The first successful read: stored silently."""

    items: Items


@dataclass(frozen=True)
class Quiet:
    """Nothing to say. `ends` is whether `until` held, which ends the watch."""

    ends: bool


@dataclass(frozen=True)
class Woke:
    """Changes for which `when` held: `items` becomes the baseline and `changes` go into a wake."""

    items: Items
    changes: tuple[Change, ...]
    ends: bool


@dataclass(frozen=True)
class Failed:
    """The read failed for `reason`; never read as the item being gone."""

    reason: FailReason


@dataclass(frozen=True)
class Later:
    """The source is not ready to answer (a mailbox still syncing). It is both a kind's read and the check made of it:
    nothing is recorded but the next try, `retry_s` on, and it is neither a failure nor an item gone."""


Check = Baseline | Quiet | Woke | Failed | Later


@dataclass(frozen=True)
class ReadFailed:
    """A kind's read of one watch failed for `reason`."""

    reason: FailReason


Read = Items | ReadFailed | Later
"""What a kind reads for one watch: its items, why it could not, or that it is not ready yet."""


@dataclass(frozen=True)
class Counts:
    """What `expire` did: `expired` live watches ended, `pruned` old ended ones deleted."""

    expired: int
    pruned: int
