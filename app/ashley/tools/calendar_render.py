"""What the calendar tool answers, made compact from the neutral records (`ashley.calendars.model`): times in the
household's zone, soonest first, only the fields a record has, and `cut` true when more events matched than shown."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..calendars.model import Agenda, Event


def _moment(value: date | datetime, zone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(zone) if value.tzinfo is not None else value.replace(tzinfo=zone)
    return datetime.combine(value, time.min, zone)


def _shown(value: date | datetime | None, zone: ZoneInfo) -> str | None:
    if value is None:
        return None
    return value.isoformat() if not isinstance(value, datetime) else _moment(value, zone).strftime("%Y-%m-%d %H:%M")


def _row(event: Event, zone: ZoneInfo) -> dict[str, object]:
    row: dict[str, object | None] = {"title": event.title, "start": _shown(event.start, zone),
                                     "end": _shown(event.end, zone), "all_day": event.all_day or None,
                                     "location": event.location, "calendar": event.calendar_id}
    return {k: v for k, v in row.items() if v is not None}


def agenda(found: Agenda, zone: ZoneInfo, limit: int) -> dict[str, object]:
    ordered = sorted(found.events, key=lambda e: _moment(e.start, zone))
    out: dict[str, object] = {
        "calendars": [{"id": c.id, "title": c.title, "source": c.source, "visibility": c.visibility}
                      for c in found.calendars],
        "events": [_row(e, zone) for e in ordered[:limit]], "cut": len(ordered) > limit}
    if found.unread:
        out["unread"] = list(found.unread)
    return out
