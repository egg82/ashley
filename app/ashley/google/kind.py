"""Google as a connection kind: a person's own Google account, connected through Google's consent screen. Its check is
Google's userinfo read with the new access token."""

from .. import services
from ..connections.kinds import ConnectionKind, OAuth, Refusal
from ..connections.oauth import OAuthProviders
from .oauth import NAME

API = "https://www.googleapis.com"
GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"


async def _check(base: str, access_token: str, person_id: int) -> Refusal | None:
    provider = services.get(OAuthProviders).get(NAME)
    return "unreachable" if provider is None else await provider.check(access_token)


GOOGLE = ConnectionKind(
    name="google", title="Google", what="your Google account",
    blurb="Connect your Google account through Google's own sign-in so she can read, draft, label and send your mail.",
    connected="Connected. Google answered for your account.",
    removed="Removed. She can’t reach your Google account now.",
    holders=frozenset({"household", "person"}), schemes=frozenset(), address_placeholder="",
    fixed_address=API,
    secret_field="token", secret_label="", secret_noun="", check=_check, ports=frozenset({"mail"}),
    refusals={"bad_url": "Google’s address is fixed",
              "key_refused": "Google turned the new access away; connect again",
              "unreachable": "nothing answered at Google in time",
              "wrong_service": "what answered is not Google’s account service"},
    connect=OAuth(NAME, ("openid", "email", GMAIL_MODIFY)))
