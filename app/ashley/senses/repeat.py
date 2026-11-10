"""When a repeating reminder comes round again, as a structured rule, never free text: every `every` days, weeks, months
or years from its first occurrence, `anchor`, a wall-clock time in the household's zone. A weekly rule may name
`weekdays` (every weekday is Monday to Friday, every week), and a monthly one `weekdays` with `nth` (the first Monday of
the month, the last Friday), a small subset of RFC 5545's BYDAY and BYSETPOS as fields. The rule may end `until` a local
date, inclusive. Occurrences keep the anchor's wall time across daylight saving: the 1st at 09:00 is 09:00 local in
winter and in summer. A monthly or yearly occurrence falls on the anchor's day, or the month's last day when the month
is shorter (a 31st is the 30th in April and the 31st again in May; 29 February is the 28th in other years). A wall time
that does not exist (the hour skipped when the clocks go forward) is read with the offset in force before the change,
so it fires an hour later in wall terms; one that happens twice (the hour repeated when they go back) is its first
instant."""

import calendar
import itertools
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, get_args
from zoneinfo import ZoneInfo

Freq = Literal["daily", "weekly", "monthly", "yearly"]
FREQS: tuple[Freq, ...] = get_args(Freq)
MAX_EVERY = 1000
MAX_COUNT = 1000
NTHS: tuple[int, ...] = (1, 2, 3, 4, -1)
"""Which of a month's weekdays: the first to the fourth, or -1 for the last."""
LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
"""A wall-clock time as she and a person's screen read and write it."""


@dataclass(frozen=True)
class Repeat:
    """`anchor` is naive: a wall-clock time in the household's zone, where the rule starts; its first occurrence is the
    anchor itself, or with `weekdays` the first day on or after it that the rule names. `weekdays` (0 Monday to 6
    Sunday, ascending) is for a weekly rule, whose weeks start on Monday, and for a monthly one, which then takes
    `nth`. `until` is the last local day an occurrence may fall on."""

    freq: Freq
    every: int
    anchor: datetime
    weekdays: tuple[int, ...] = ()
    nth: int | None = None
    until: date | None = None

    def __post_init__(self) -> None:
        if self.freq not in FREQS:
            raise ValueError("freq is daily, weekly, monthly or yearly")
        if not 1 <= self.every <= MAX_EVERY:
            raise ValueError(f"every is between 1 and {MAX_EVERY}")
        if self.anchor.tzinfo is not None:
            raise ValueError("anchor is a wall-clock time, without a zone")
        self._check_weekdays()
        if self.until is not None and self.until < self.anchor.date():
            raise ValueError("until is not before the start")

    def _check_weekdays(self) -> None:
        if not self.weekdays:
            if self.nth is not None:
                raise ValueError("nth goes with weekdays")
            return
        if self.freq not in ("weekly", "monthly"):
            raise ValueError("weekdays are for a weekly or monthly repeat")
        if list(self.weekdays) != sorted(set(self.weekdays)) or not all(0 <= d <= 6 for d in self.weekdays):
            raise ValueError("weekdays are 0 (Monday) to 6 (Sunday), each once, ascending")
        if (self.freq == "monthly") != (self.nth is not None) or (self.nth is not None and self.nth not in NTHS):
            raise ValueError("a monthly repeat on weekdays takes nth 1 to 4 or -1; a weekly one takes none")


def freq_of(raw: object) -> Freq | None:
    """`raw` as a frequency; None when it is not one."""
    for freq in FREQS:
        if freq == raw:
            return freq
    return None


def instant(local: datetime, zone: ZoneInfo) -> datetime:
    """The UTC instant of the naive wall-clock time `local` in `zone`."""
    return local.replace(tzinfo=zone, fold=0).astimezone(UTC)


def occurrence(repeat: Repeat, k: int) -> datetime:
    """The `k`th occurrence (0 is the anchor) as a naive wall-clock time, for a rule without `weekdays`; a rule that
    names them is walked by `occurrences` and `starts`, whose first occurrence is not the anchor."""
    a, step = repeat.anchor, k * repeat.every
    if repeat.freq == "daily":
        return a + timedelta(days=step)
    if repeat.freq == "weekly":
        return a + timedelta(weeks=step)
    months = step * (12 if repeat.freq == "yearly" else 1)
    year, month = divmod(a.month - 1 + months, 12)
    year, month = a.year + year, month + 1
    return a.replace(year=year, month=month, day=min(a.day, calendar.monthrange(year, month)[1]))


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    days = calendar.monthrange(year, month)[1]
    if nth > 0:
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    last = first + timedelta(days=days - 1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _period(repeat: Repeat, p: int) -> list[datetime]:
    """The occurrences of the `p`th period of the rule (0 holds the anchor), ascending, none before the anchor."""
    a = repeat.anchor
    if not repeat.weekdays:
        return [occurrence(repeat, p)]
    if repeat.freq == "weekly":
        monday = a.date() - timedelta(days=a.weekday()) + timedelta(weeks=p * repeat.every)
        days = [monday + timedelta(days=d) for d in repeat.weekdays]
    else:
        year, month = divmod(a.month - 1 + p * repeat.every, 12)
        nth = repeat.nth if repeat.nth is not None else 1
        days = sorted(_nth_weekday(a.year + year, month + 1, d, nth) for d in repeat.weekdays)
    return [at for at in (datetime.combine(d, a.time()) for d in days) if at >= a]


def _stream(repeat: Repeat, first_period: int = 0) -> Iterator[datetime]:
    """The rule's occurrences, naive and ascending, from period `first_period`, ending at `until`."""
    for p in itertools.count(first_period):
        for local in _period(repeat, p):
            if repeat.until is not None and local.date() > repeat.until:
                return
            yield local


def starts(repeat: Repeat) -> datetime | None:
    """The first occurrence as a naive wall-clock time; None when `until` leaves none."""
    return next(_stream(repeat), None)


def until_after(repeat: Repeat, count: int) -> date:
    """The local day of the rule's `count`th occurrence (1 to `MAX_COUNT`), so a rule that runs `count` times ends
    there. `repeat` has no `until` of its own. Raises ValueError otherwise."""
    if repeat.until is not None or not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count is 1 to {MAX_COUNT}, for a rule with no end")
    return list(itertools.islice(_stream(repeat), count))[-1].date()


def next_after(repeat: Repeat, after: datetime, zone: ZoneInfo) -> datetime | None:
    """The UTC instant of the first occurrence strictly after the aware instant `after`; None when the rule has ended."""
    first = max(0, _estimate(repeat, after.astimezone(zone).replace(tzinfo=None)) - 1)
    for local in _stream(repeat, first):
        got = instant(local, zone)
        if got > after:
            return got
    return None


def _estimate(repeat: Repeat, local: datetime) -> int:
    """A count of periods from the anchor's to `local`'s that is never more than one past the true one."""
    if local <= repeat.anchor:
        return 0
    if repeat.freq in ("daily", "weekly"):
        days = (local - repeat.anchor).days
        return days // (repeat.every * (7 if repeat.freq == "weekly" else 1))
    months = (local.year - repeat.anchor.year) * 12 + local.month - repeat.anchor.month
    return months // (repeat.every * (12 if repeat.freq == "yearly" else 1))


_KEYS = {"freq", "every", "anchor", "weekdays", "nth", "until"}
_REQUIRED = {"freq", "every", "anchor"}


def to_json(repeat: Repeat) -> dict[str, object]:
    """The rule as stored; a field it does not use is left out, so a rule without them is stored as it always was."""
    out: dict[str, object] = {"freq": repeat.freq, "every": repeat.every,
                              "anchor": repeat.anchor.isoformat(timespec="minutes")}
    if repeat.weekdays:
        out["weekdays"] = list(repeat.weekdays)
    if repeat.nth is not None:
        out["nth"] = repeat.nth
    if repeat.until is not None:
        out["until"] = repeat.until.isoformat()
    return out


def _ints(raw: object) -> tuple[int, ...] | None:
    loose: Any = raw
    if not isinstance(raw, list):
        return None
    items = list[object](loose)
    return tuple(d for d in items if isinstance(d, int)) if all(isinstance(d, int) for d in items) else None


def from_json(raw: Mapping[str, object]) -> Repeat:
    """Raises ValueError for anything `to_json` does not make."""
    freq = freq_of(raw.get("freq"))
    every, anchor, weekdays, nth, until = (raw.get(k) for k in ("every", "anchor", "weekdays", "nth", "until"))
    if not _REQUIRED <= set(raw) <= _KEYS or freq is None or not isinstance(every, int) or not isinstance(anchor, str):
        raise ValueError("a repeat is freq, every and anchor, and may name weekdays, nth and until")
    days = _ints(weekdays)
    if weekdays is not None and days is None:
        raise ValueError("weekdays are a list of integers")
    if (nth is not None and not isinstance(nth, int)) or (until is not None and not isinstance(until, str)):
        raise ValueError("nth is an integer and until a date")
    return Repeat(freq, every, datetime.fromisoformat(anchor), days or (), nth,
                  None if until is None else date.fromisoformat(until))
