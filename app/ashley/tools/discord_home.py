"""The port to her home channel on a household's Discord server (`ashley.services`, `DiscordServer.home_channel_id`):
her own messages there, its topic and her pins, over Discord's REST API with the bot's token in force. It touches only
the channel it is given, and pins or unpins only a message the bot wrote. The server's owner grants Manage Channels and
Manage Messages on that channel alone, as a channel permission override."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..services import Service

Reason = Literal["no_token", "refused", "not_found", "not_hers", "unreachable", "unexpected"]
"""Why a call failed: no bot token is set, or it cannot be read; Discord turned the token or the channel's permission
away (401, 403); no such channel or message (404); the message is not the bot's; no answer, a rate limit or a server
error; an answer that is not what was asked for, or one Discord refused for another reason (400, e.g. too many pins)."""


class HomeFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True)
class Mine:
    """One of her own messages in the channel: its snowflake `id`, when it was `at` sent (ISO 8601 as Discord gives it),
    its `text` and whether it is `pinned`."""

    id: int
    at: str
    text: str
    pinned: bool


class HomeChannel(Service):
    @classmethod
    def null(cls) -> "HomeChannel":
        return NullHomeChannel()

    @abstractmethod
    async def mine(self, channel_id: int, count: int) -> list[Mine]:
        """Her messages among the channel's latest `count` (1 to 100), plus every pinned one of hers, oldest first.
        Raises HomeFailed."""

    @abstractmethod
    async def set_topic(self, channel_id: int, topic: str) -> None:
        """Set the channel's topic (at most 1024 characters; empty clears it). Raises HomeFailed."""

    @abstractmethod
    async def pin(self, channel_id: int, message_id: int, pinned: bool) -> None:
        """Pin (`pinned`) or unpin the message, which must be the bot's own in this channel (else `not_hers`). Raises
        HomeFailed."""


class NullHomeChannel(HomeChannel):
    async def mine(self, channel_id: int, count: int) -> list[Mine]:
        raise HomeFailed("no_token")

    async def set_topic(self, channel_id: int, topic: str) -> None:
        raise HomeFailed("no_token")

    async def pin(self, channel_id: int, message_id: int, pinned: bool) -> None:
        raise HomeFailed("no_token")
