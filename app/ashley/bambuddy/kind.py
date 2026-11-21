"""Bambuddy as a connection kind: the household's 3D printing, checked by one read of its printers."""

from ..connections.kinds import ConnectionKind, Refusal
from . import client
from .check import printers_seen

NAME = "bambuddy"

_REFUSED: dict[client.Reason, Refusal] = {"refused": "key_refused", "unreachable": "unreachable",
                                          "not_bambuddy": "wrong_service", "not_found": "wrong_service",
                                          "rejected": "wrong_service"}


async def _check(base: str, api_key: str, person_id: int) -> Refusal | None:
    try:
        await printers_seen(base, api_key)
    except client.BambuddyFailed as e:
        return _REFUSED[e.reason]
    return None


BAMBUDDY = ConnectionKind(
    name=NAME, title="Bambuddy", what="3D printing",
    blurb="Let her see what the household’s printers are doing, what is loaded in each AMS slot, what filament is in "
          "stock and what a model in the print library needs, and, once you agree, queue a print for you. A key that may "
          "read status, the library and the inventory is enough to look; add permission to queue and to manage the "
          "library for her to queue, and never permission to control a printer.",
    connected="Connected. She can see the household’s printers and filament.",
    removed="Removed. She can’t see the printers now.",
    holders=frozenset({"household"}), schemes=frozenset({"http", "https"}), address_placeholder="https://bambuddy.example",
    secret_field="api_key", secret_label="API key, from Bambuddy’s settings", secret_noun="key", check=_check,
    ports=frozenset({"printing", "stock"}),
    refusals={"bad_url": "the address is an http or https address of Bambuddy, with nothing after it but a path",
              "key_refused": "Bambuddy turned that key away; make one in Bambuddy's settings, with permission to read "
                             "status, and paste it here",
              "unreachable": "nothing answered at that address in time",
              "wrong_service": "what answered at that address is not Bambuddy"})
