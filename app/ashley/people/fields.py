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


def is_locale(tag: str) -> bool:
    """Whether `tag` is a BCP 47 language tag of language, optional script and optional region, in their canonical case:
    `en`, `en-US`, `es-419`, `zh-Hans-CN`. Variants and extensions are refused, since nothing here reads them."""
    return _LOCALE.fullmatch(tag) is not None
