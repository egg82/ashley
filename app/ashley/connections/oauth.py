"""An OAuth provider as a port (`decisions.md`, "A kind's secret can come from OAuth"): where to send the browser, what a
callback's code is worth, how a refresh token is turned into a new access token. Authorization code with PKCE (S256).
A provider is registered by name in `OAuthProviders` only when its client is configured, so an unset provider is
absent and connecting through it answers 503. Google's is `ashley.google.oauth.GoogleOAuth`."""

from abc import ABC, abstractmethod

from ..services import Service
from .kinds import Refusal
from .model import Grant

CALLBACK_PATH = "/api/connections/oauth/{provider}/callback"
"""On `public_url`, with the provider's name filled in; registered on its OAuth client as is."""


class OAuthUnavailable(Exception):
    """The provider could not be reached, or answered with an error that is not about the grant. Transient."""


class OAuthFailed(Exception):
    """The provider refused the callback's code, or answered something unreadable. The message is in words of ours,
    never a token or a URL."""


class OAuthRefused(Exception):
    """The provider refused a refresh token: the grant is revoked or expired (`invalid_grant`). The connection needs
    its person to connect again."""


class OAuthProvider(ABC):
    @abstractmethod
    def authorize_url(self, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
        """The provider's consent URL for `scopes`, asking for a refresh token."""

    @abstractmethod
    async def redeem(self, code: str, verifier: str) -> Grant:
        """The grant a callback's `code` is worth, always with a refresh token. Raises OAuthFailed, or OAuthUnavailable."""

    @abstractmethod
    async def refresh(self, refresh_token: str) -> Grant:
        """A new access token for `refresh_token`; its `refresh_token` is set only when the provider rotated it.
        Raises OAuthRefused, or OAuthUnavailable."""

    @abstractmethod
    async def check(self, access_token: str) -> Refusal | None:
        """The one authenticated read that proves the token reaches an account (for Google, its userinfo): None when it
        answered, else why not."""


class OAuthProviders(Service):
    """The configured providers by name. Unregistered: none."""

    def __init__(self, providers: dict[str, OAuthProvider] | None = None) -> None:
        self._providers = dict(providers or {})

    @classmethod
    def null(cls) -> "OAuthProviders":
        return cls()

    def get(self, name: str) -> OAuthProvider | None:
        return self._providers.get(name)
