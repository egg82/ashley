"""When something happened, as she is shown it: the household's local weekday, date and 24-hour time
(`Sun 1 Nov 2026 10:22`), the one format for every time in her prompt and tool results. It never depends on the clock
now, so a line shown twice is the same bytes."""

from datetime import datetime, tzinfo


def stamp(at: datetime, zone: tzinfo) -> str:
    """`at` in `zone`, to the minute."""
    local = at.astimezone(zone)
    return f"{local:%a} {local.day} {local:%b %Y} {local:%H:%M}"
