"""The link a browser pod opens to see a bench. A token is `<payload>.<mac>`: the payload names the household, the
person whose bench it is, the bench, optionally one piece, and when the link stops working; the mac is HMAC-SHA256
under the app's link key over the payload with a `look.` prefix, so a file link (`ashley.files.links`) is never a look
link. The token is the only credential. Pure; the clock is a parameter."""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

PAGE = "/look/"
PURPOSE = "look."
PICTURE_PURPOSE = "lookpic."
PICTURE_PATH = "/api/looks/"


@dataclass(frozen=True)
class Grant:
    """What a valid link lets its holder read: bench `bench_id` of `person_id` in `household_id`, as that person would
    see it, narrowed to piece `piece_id` when it is not None. `expires_at` is when it stops (Unix seconds)."""

    household_id: int
    person_id: int
    bench_id: int
    piece_id: int | None
    expires_at: int


def mint(key: bytes, grant: Grant) -> str:
    """The token for `grant`."""
    payload = _b64(json.dumps({"h": grant.household_id, "p": grant.person_id, "b": grant.bench_id,
                               "i": grant.piece_id, "e": grant.expires_at}, separators=(",", ":")).encode())
    return f"{payload}.{_b64(_mac(key, payload))}"


def check(key: bytes, token: str, now: float) -> Grant | None:
    """The grant `token` carries, None when it is malformed, forged or expired."""
    payload, _, mac = token.partition(".")
    try:
        if not hmac.compare_digest(_b64(_mac(key, payload)), mac):
            return None
        raw = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        piece = raw["i"]
        grant = Grant(int(raw["h"]), int(raw["p"]), int(raw["b"]), None if piece is None else int(piece), int(raw["e"]))
    except (ValueError, KeyError, TypeError, binascii.Error):
        return None
    return grant if now < grant.expires_at else None


@dataclass(frozen=True)
class Picture:
    """What a valid picture link lets its holder read: look picture `household_id`/`sha256`, served as `media_type`,
    until `expires_at` (Unix seconds)."""

    household_id: int
    sha256: str
    media_type: str
    expires_at: int


def mint_picture(key: bytes, picture: Picture) -> str:
    """The token for `picture`; its mac is under its own purpose, so it is no page link and no file link."""
    payload = _b64(json.dumps({"h": picture.household_id, "s": picture.sha256, "m": picture.media_type,
                               "e": picture.expires_at}, separators=(",", ":")).encode())
    return f"{payload}.{_b64(_mac(key, payload, PICTURE_PURPOSE))}"


def check_picture(key: bytes, token: str, now: float) -> Picture | None:
    """The picture `token` carries, None when it is malformed, forged or expired."""
    payload, _, mac = token.partition(".")
    try:
        if not hmac.compare_digest(_b64(_mac(key, payload, PICTURE_PURPOSE)), mac):
            return None
        raw = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        found = Picture(int(raw["h"]), str(raw["s"]), str(raw["m"]), int(raw["e"]))
    except (ValueError, KeyError, TypeError, binascii.Error):
        return None
    return found if now < found.expires_at else None


def _mac(key: bytes, payload: str, purpose: str = PURPOSE) -> bytes:
    return hmac.new(key, (purpose + payload).encode(), hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")
