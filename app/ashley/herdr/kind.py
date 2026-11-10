"""The herdr bridge as a connection kind: a person's own Claude Code sessions, checked by the bridge answering
`whoami` for them. The address carries the bridge's certificate fingerprint (`https://host:7843#sha256=<hex>`), since
the row holds an address and one secret and the fingerprint is neither typed apart nor secret."""

from .. import services
from ..connections.kinds import ConnectionKind, Refusal
from .bridge import Bridge
from .model import Access, BridgeFailed, Reason

_REFUSED: dict[Reason, Refusal] = {"bad_token": "key_refused", "wrong_person": "key_refused",
                                   "herdr_unavailable": "unreachable", "unconfirmed": "unreachable"}


async def _check(base: str, token: str, person_id: int) -> Refusal | None:
    try:
        await services.get(Bridge).whoami(Access.of(base, token, person_id))
    except BridgeFailed as e:
        return _REFUSED.get(e.reason, "wrong_service")
    return None


HERDR = ConnectionKind(
    name="herdr", title="Claude Code", what="your sessions",
    blurb="Let her see and drive your Claude Code sessions through the bridge you run beside your herdr: list them, "
          "read a screen, send a prompt to one that is ready, and start or close one. Only in a chat that is yours "
          "alone.",
    connected="Connected. She can reach your Claude Code sessions in your own chat.",
    removed="Removed. She can’t reach your Claude Code sessions now.",
    holders=frozenset({"person"}), schemes=frozenset({"https"}), address_placeholder="https://host:7843#sha256=<fingerprint>",
    secret_field="token", secret_label="Token, printed once when you set the bridge up", secret_noun="token",
    check=_check, pinned=True, ports=frozenset({"herdr"}),
    refusals={"bad_url": "the address is the bridge’s https address followed by #sha256= and the fingerprint it "
                         "printed, 64 hex digits",
              "key_refused": "the bridge turned that token away, or serves another person; set it up again to get "
                             "a new token",
              "unreachable": "nothing answered at that address in time, or herdr is not running there",
              "wrong_service": "what answered is not your bridge: its certificate is not the one with that "
                               "fingerprint, or it does not speak the bridge’s API"})
