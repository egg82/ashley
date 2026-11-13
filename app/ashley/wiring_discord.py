"""Discord's clients wired: the sign-in provider when `DISCORD_OAUTH_CLIENT_ID` is set, and the channel posts client
that reads the bot token in force on each call."""

from collections.abc import Callable, Coroutine
from typing import Any

import httpx2

from . import services
from .channels.discord.token_in_force import TokenInForce
from .connections.connections import Connections
from .settings import Settings
from .signin.discord import CALLBACK_PATH as DISCORD_CALLBACK, DiscordOAuth
from .signin.discord_http import App as DiscordApp, HttpDiscordOAuth
from .tools.discord_posts import ChannelPosts
from .tools.discord_posts_http import HttpChannelPosts


def wire_discord(settings: Settings, closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    if settings.discord_oauth_client_id:
        discord_http = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
        closers.append(discord_http.aclose)
        services.register(DiscordOAuth, HttpDiscordOAuth(DiscordApp(
            settings.discord_oauth_client_id, settings.discord_oauth_client_secret,
            settings.public_url + DISCORD_CALLBACK), discord_http))
    posts_http = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
    closers.append(posts_http.aclose)
    services.register(ChannelPosts, HttpChannelPosts(
        TokenInForce(lambda: services.get(Connections), settings.discord_bot_token), posts_http))
