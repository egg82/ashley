"""The wire shape of the kiosk's glance."""

from typing import Literal

from pydantic import BaseModel


class KioskEvent(BaseModel):
    """One calendar event on the household's wall clock: `time` is `HH:MM`, null for an all-day event."""

    title: str
    day: Literal["today", "tomorrow"]
    time: str | None


class KioskGlance(BaseModel):
    """What the kiosk shows at a glance, shared things only. `home` is the first names of the household's people who
    are home: empty when everyone known is away, null when it cannot be known. `not_connected` names the glance's
    sources that have nothing behind them yet, which the page shows as not connected, never with sample data.
    `locale` (BCP 47) and `clock` are how the household writes dates and times, null when the household could not be
    read; the time itself is the tablet's own. `calendar` is today's and tomorrow's events of the calendars the household
    listed, in order, title and time only; empty when there are none, null when they could not be read or `calendar` is
    in `not_connected`."""

    home: list[str] | None
    not_connected: list[Literal["calendar", "reminders"]]
    locale: str | None
    clock: Literal["12h", "24h"] | None
    calendar: list[KioskEvent] | None
