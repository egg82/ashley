"""Whether Bambuddy answers with a key: one read of its printers, as a connection is added."""

from .. import services
from .client import Bambuddy
from .wire import Printers, parsed


async def printers_seen(base: str, api_key: str) -> int:
    """How many printers Bambuddy at `base` shows this key. Raises BambuddyFailed."""
    return len(parsed(Printers, await services.get(Bambuddy).get(base, api_key, "/api/v1/printers/", {})).root)
