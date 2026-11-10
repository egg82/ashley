"""One mail call's bookkeeping, the same for every adapter: it runs, the connection it went through is marked answered when
it did, and `mail.call` is logged with the connection, the call, the status (`ok` or the `MailFailed` reason), the count
and the duration, never an address, a subject, a body, a query or a token."""

import logging
import time
from collections.abc import Awaitable, Callable

from .. import logs
from ..connections import answered
from .model import Account, MailFailed

log = logging.getLogger("ashley.mail")


async def logged[T](call: str, account: Account, work: Callable[[], Awaitable[tuple[T, int]]]) -> T:
    """The result of `work`, which gives it with the count to log. Raises what `work` raises."""
    started, status, count = time.monotonic(), "ok", 0
    try:
        got, count = await work()
        await answered.record(account.connection_id)
        return got
    except MailFailed as e:
        status = e.reason
        raise
    finally:
        logs.info(log, "mail.call", connection=account.connection_id, call=call, status=status, count=count,
                  duration_ms=int((time.monotonic() - started) * 1000))
