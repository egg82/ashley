"""One Discord message as the adapter sees it, and the time inside a snowflake id."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_EPOCH_MS = 1420070400000   # Discord's epoch, the first second of 2015, in ms since the Unix epoch
_UNIX = datetime(1970, 1, 1, tzinfo=UTC)
_MS = timedelta(milliseconds=1)


@dataclass(frozen=True)
class Message:
    """One Discord message as the adapter sees it. Ids are snowflakes. `guild_id` None means a DM. `mentions_me`:
    she is in the message's user mentions. `replies_to_me`: it replies to a message she wrote. `forwarded` is the
    text of the messages forwarded in it (the snapshots of its `message_reference`), joined by a blank line, "" when
    it forwards none. `content` and `forwarded` are never logged."""

    id: int
    channel_id: int
    guild_id: int | None
    author_id: int
    author_is_bot: bool
    content: str
    mentions_me: bool
    replies_to_me: bool
    forwarded: str = ""


def sent_at(snowflake: int) -> datetime:
    """When a snowflake was made, UTC: `(snowflake >> 22) + 1420070400000` ms since the epoch."""
    return _UNIX + ((snowflake >> 22) + _EPOCH_MS) * _MS


def snowflake_at(at: datetime) -> int:
    """The smallest snowflake made at `at` (aware), so every message sent at or after `at` has a greater or equal id."""
    return (-((_UNIX - at) // _MS) - _EPOCH_MS) << 22
