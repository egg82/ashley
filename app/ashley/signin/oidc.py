"""The OIDC provider as a service (`ashley.services`): where to send a browser to sign in, and who a callback's code
says signed in. Authorization code with PKCE (S256) for a confidential client. The one implementation is
`ashley.signin.provider.OidcProvider`, wired only when its settings are; unwired, every call raises
OidcUnavailable and the sign-in routes answer 503."""

import base64
import hashlib
import secrets
from abc import abstractmethod

from ..services import Service
from .model import Identity


class OidcUnavailable(Exception):
    """Sign-in is not configured, or the provider could not be reached. A 503."""


class SignInFailed(Exception):
    """The callback is not a sign-in: the provider refused the code, or its ID token did not verify. The message names
    which, in words of ours, never a token or a URL."""


def pkce() -> tuple[str, str]:
    """(verifier, its S256 challenge), RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class Oidc(Service):
    @classmethod
    def null(cls) -> "Oidc":
        return NullOidc()

    @abstractmethod
    async def authorize_url(self, state: str, nonce: str, challenge: str) -> str:
        """The provider's authorization URL for this sign-in. Raises OidcUnavailable."""

    @abstractmethod
    async def identify(self, code: str, verifier: str, nonce: str) -> Identity:
        """Redeem the callback's `code` and verify the ID token (signature, issuer, audience, expiry, `nonce`). Raises
        SignInFailed, or OidcUnavailable when the provider cannot be reached."""


class NullOidc(Oidc):
    """Sign-in not configured: every call raises OidcUnavailable."""

    async def authorize_url(self, state: str, nonce: str, challenge: str) -> str:
        raise OidcUnavailable("sign-in is not configured")

    async def identify(self, code: str, verifier: str, nonce: str) -> Identity:
        raise OidcUnavailable("sign-in is not configured")
