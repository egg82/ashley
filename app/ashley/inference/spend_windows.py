"""The spans the spend page reports: today, the last 7 days (today and the six before it) and this calendar month,
each starting at local midnight in the household's time zone."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

WindowName = Literal["today", "week", "month"]


@dataclass(frozen=True)
class Window:
    """`starts` is an instant (UTC offset aware): the first moment of the span, which runs to now."""

    name: WindowName
    starts: datetime


def windows(now: datetime, zone: ZoneInfo) -> tuple[Window, Window, Window]:
    """The three spans as of `now`. A day is a calendar day in `zone`, so a span across a daylight-saving change holds
    that day's real length rather than 24 hours."""
    local = now.astimezone(zone)
    today = local.date()

    def midnight(day: datetime) -> datetime:
        return datetime.combine(day.date(), time(), zone)

    return (Window("today", midnight(local)),
            Window("week", midnight(local - timedelta(days=6))),
            Window("month", datetime.combine(today.replace(day=1), time(), zone)))
