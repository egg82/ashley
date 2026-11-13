"""What a household's fields may hold, checked the same way by the admin CLI and the web route."""

import re
from zoneinfo import ZoneInfo

_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-(?:[A-Z]{2}|[0-9]{3}))?$")
PROFILE_MAX = 8000
"""The most characters a profile holds: it is in every system prompt."""


def is_timezone(name: str) -> bool:
    """Whether `name` is an IANA zone name (`America/Denver`) this host's zone data knows."""
    try:
        ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return False
    return True


def is_location(latitude: float | None, longitude: float | None) -> bool:
    """Whether the pair is a house's location: both None (none set), or both finite degrees within range."""
    if latitude is None or longitude is None:
        return latitude is None and longitude is None
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def is_locale(tag: str) -> bool:
    """Whether `tag` is a BCP 47 language tag of language, optional script and optional region, in their canonical case:
    `en`, `en-US`, `es-419`, `zh-Hans-CN`. Variants and extensions are refused, since nothing here reads them."""
    return _LOCALE.fullmatch(tag) is not None


def is_quiet_window(start: int, end: int, timezone: str) -> bool:
    """Whether the hours are a quiet window: each a whole hour from 0 to 23, not the same one, in a zone this host knows."""
    return 0 <= start <= 23 and 0 <= end <= 23 and start != end and is_timezone(timezone)
