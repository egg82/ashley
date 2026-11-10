"""Her synthesised voice streamed to a player, timed: the chunks pass through unchanged and one line is logged when the
stream ends or is dropped (`voice.clip`, `voice.turn`)."""

import logging
import time
from collections.abc import AsyncIterator, Mapping

from .. import logs

log = logging.getLogger("ashley.api.voice")


async def timed(chunks: AsyncIterator[bytes], asked: float, provider: str, model: str, event: str,
                who: Mapping[str, object], since_wake_ms: int | None = None) -> AsyncIterator[bytes]:
    """`chunks` as they come, then `event` logged with `who` (ids), `tts_provider` and `tts_model` (the route that
    spoke), `tts_first_byte_ms` (`asked`, a `time.perf_counter()` reading, to the first byte; None when none came),
    `total_ms` when `since_wake_ms` is given (that plus the first byte; None when none came), the bytes sent and
    whether the stream ended `complete`."""
    first: float | None = None
    sent, complete = 0, False
    try:
        async for chunk in chunks:
            if first is None:
                first = time.perf_counter()
            sent += len(chunk)
            yield chunk
        complete = True
    finally:
        first_ms = None if first is None else int((first - asked) * 1000)
        total = {} if since_wake_ms is None else {"total_ms": None if first_ms is None else since_wake_ms + first_ms}
        logs.info(log, event, **who, tts_provider=provider, tts_model=model, tts_first_byte_ms=first_ms, **total,
                  bytes=sent, complete=complete)
