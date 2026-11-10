"""Discord's OAuth2 as a service (`ashley.services`), for a signed-in person to prove which Discord account is theirs:
where to send the browser, and which Discord user a callback's code names. Authorization code with PKCE (S256), scope
`identify` only. Its one implementation is `ashley.signin.discord_http.HttpDiscordOAuth`, wired only when its settings
are; unwired, `configured` is False and every call raises LinkUnavailable. No Discord token outlives the call that
redeemed it: it is revoked once the user is read."""

from abc import abstractmethod
from dataclasses import dataclass

from ..services import Service

SYSTEM = "discord"
CALLBACK_PATH = "/api/accounts/discord/callback"   # on `public_url`; registered on the Discord application as is


class LinkUnavailable(Exception):
    """Linking is not configured, or Discord could not be reached. A 503."""


class LinkFailed(Exception):
    """The callback names no Discord user: Discord refused the code, or answered something unreadable. The message
    names which, in words of ours, never a token or a URL."""


@dataclass(frozen=True)
class DiscordUser:
    """Who Discord says authorized: `id`, its snowflake, stable for the account's life, and `handle`, its username
    (with `#discriminator` on an account that still has one), which may change and so is only ever shown."""

    id: str
    handle: str


class DiscordOAuth(Service):
    @classmethod
    def null(cls) -> "DiscordOAuth":
        return NullDiscordOAuth()

    @abstractmethod
    def configured(self) -> bool:
        """Whether linking is wired at all, so a page can say so before anyone tries."""

    @abstractmethod
    async def authorize_url(self, state: str, challenge: str) -> str:
        """Discord's authorization URL for this link. Raises LinkUnavailable."""

    @abstractmethod
    async def identify(self, code: str, verifier: str) -> DiscordUser:
        """Redeem the callback's `code` and read who it names. Raises LinkFailed, or LinkUnavailable when Discord
        cannot be reached."""


class NullDiscordOAuth(DiscordOAuth):
    """Linking not configured: every call raises LinkUnavailable."""

    def configured(self) -> bool:
        return False

    async def authorize_url(self, state: str, challenge: str) -> str:
        raise LinkUnavailable("Discord linking is not configured")

    async def identify(self, code: str, verifier: str) -> DiscordUser:
        raise LinkUnavailable("Discord linking is not configured")
