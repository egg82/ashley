"""A household's satellites' Noise key as a connection kind of the `voice` port: the pre-shared key (base64, 32 bytes) its
ESPHome devices encrypt their native API with (`api: encryption: key`). The household holds it, one key for all its
satellites. There is no service to ask, so the check reads the key's shape only; a device that rejects it is seen as
`voice.connect_failed`. The address is a fixed placeholder: satellites are reached at their own hosts."""

import base64
import binascii

from ...connections.kinds import ConnectionKind, Refusal

NAME = "esphome"
API = "esphome://satellites"
KEY_BYTES = 32


async def check(base: str, key: str, person_id: int) -> Refusal | None:
    """None when `key` is base64 of `KEY_BYTES` bytes; `key_refused` otherwise. Makes no call."""
    try:
        raw = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError):
        return "key_refused"
    return None if len(raw) == KEY_BYTES else "key_refused"


KIND = ConnectionKind(
    name=NAME, title="Voice satellites", what="her voice satellites",
    blurb="The encryption key your ESPHome voice satellites share. She talks to them as a satellite of this household while it is set.",
    connected="Saved. She uses this key for your satellites from now on.",
    removed="Removed. Her satellites stay unreachable until a key is set again.",
    holders=frozenset({"household"}), schemes=frozenset({"esphome"}), address_placeholder="",
    secret_field="api_key", secret_label="Encryption key, from the devices' ESPHome config", secret_noun="key",
    check=check, ports=frozenset({"voice"}), fixed_address=API,
    refusals={"bad_url": "Satellites are reached at their own addresses",
              "key_refused": "That is not an ESPHome encryption key (base64 of 32 bytes)",
              "unreachable": "The key could not be checked right now; try again shortly",
              "wrong_service": "That is not an ESPHome encryption key"})
