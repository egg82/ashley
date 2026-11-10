"""A fake Discord OAuth2 port, in process: `authorize` plays the browser at Discord's authorization page, reading the
URL the app sent it to and handing back the code Discord would put on the callback; `identify` redeems that code only
with the verifier whose S256 challenge it was issued for."""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from ashley.signin.discord import DiscordOAuth, DiscordUser, LinkFailed, LinkUnavailable

AUTHORIZE = "https://discord.test/oauth2/authorize"


@dataclass
class FakeDiscord(DiscordOAuth):
    """`user` is who authorizes next. `down` makes every call raise LinkUnavailable; `refuse` makes the code refused."""

    user: DiscordUser = field(default_factory=lambda: DiscordUser("80351110224678912", "zqHANDLE"))
    down: bool = False
    refuse: bool = False
    grants: dict[str, tuple[str, DiscordUser]] = field(default_factory=dict[str, tuple[str, DiscordUser]])

    def configured(self) -> bool:
        return True

    async def authorize_url(self, state: str, challenge: str) -> str:
        if self.down:
            raise LinkUnavailable("down")
        return f"{AUTHORIZE}?state={state}&code_challenge={challenge}&scope=identify"

    def authorize(self, url: str) -> tuple[str, str]:
        """(code, state) for the authorization URL the app answered."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert query["scope"] == "identify"
        code = secrets.token_urlsafe(16)
        self.grants[code] = (query["code_challenge"], self.user)
        return code, query["state"]

    async def identify(self, code: str, verifier: str) -> DiscordUser:
        if self.down:
            raise LinkUnavailable("down")
        challenge, user = self.grants.pop(code, ("", self.user))
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if self.refuse or challenge != expected:
            raise LinkFailed("token endpoint answered 400")
        return user
