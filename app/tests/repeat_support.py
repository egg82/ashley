"""`next_after` for the tests of rules that never end."""

from datetime import datetime
from zoneinfo import ZoneInfo

from ashley.senses.repeat import Repeat, next_after


def next_of(repeat: Repeat, after: datetime, zone: ZoneInfo) -> datetime:
    """The next occurrence of `repeat` after `after`; the rule has one."""
    got = next_after(repeat, after, zone)
    assert got is not None
    return got
