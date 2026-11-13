"""The port to a Discord channel's recent messages (`ashley.services`), read over Discord's REST API with the bot's token
in force (`ashley.channels.discord.token_in_force`). It reads the channel it is asked for and changes nothing."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..services import Service

Reason = Literal["no_token", "refused", "not_found", "unreachable", "unexpected"]
"""Why a read failed: no bot token is set, or it cannot be read; Discord turned the token or the channel's permission
away (401, 403); no such channel (404); no answer, a rate limit or a server error; an answer that is not messages."""


class PostsFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True)
class Post:
    """One message: its snowflake `id`, the author's display name, whether a bot wrote it, when it was `at` sent (ISO
    8601 as Discord gives it) and its `text`. Everything but `id` was written outside her control."""

    id: int
    author: str
    bot: bool
    at: str
    text: str


class ChannelPosts(Service):
    @classmethod
    def null(cls) -> "ChannelPosts":
        return NullChannelPosts()

    @abstractmethod
    async def recent(self, channel_id: int, count: int) -> list[Post]:
        """Up to `count` (1 to 100) of the channel's latest messages, oldest first. Raises PostsFailed."""


class NullChannelPosts(ChannelPosts):
    async def recent(self, channel_id: int, count: int) -> list[Post]:
        raise PostsFailed("no_token")
