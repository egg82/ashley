"""Sure as a connection kind: the household's finances, checked by one read of its accounts."""

from ..connections.kinds import ConnectionKind, Refusal
from . import client
from .check import accounts_seen

_REFUSED: dict[client.Reason, Refusal] = {"refused": "key_refused", "unreachable": "unreachable",
                                          "not_sure": "wrong_service"}


async def _check(base: str, api_key: str, person_id: int) -> Refusal | None:
    try:
        await accounts_seen(base, api_key)
    except client.SureFailed as e:
        return _REFUSED[e.reason]
    return None


SURE = ConnectionKind(
    name="sure", title="Sure", what="finances",
    blurb="Let her read the household’s accounts, transactions and net worth in Sure. She only reads, and only in a "
          "chat that is yours alone.",
    connected="Connected. She can read the household’s finances for whoever asks in their own chat.",
    removed="Removed. She can’t read Sure now.",
    holders=frozenset({"household"}), schemes=frozenset({"https"}), address_placeholder="https://money.example",
    secret_field="api_key", secret_label="API key, from Sure’s settings", secret_noun="key", check=_check,
    ports=frozenset({"ledger"}),
    refusals={"bad_url": "the address is an https address of Sure, with nothing after it but a path",
              "key_refused": "Sure turned that key away; make one in Sure's settings and paste it here",
              "unreachable": "nothing answered at that address in time",
              "wrong_service": "what answered at that address is not Sure"})
