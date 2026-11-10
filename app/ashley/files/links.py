"""Short-lived download links. A link is a token, `<payload>.<mac>`: the payload names the object (household, sha256),
its media type, whether the page may show it in place, and when the link stops working; the mac is HMAC-SHA256 under
the app's link key, shared by every pod of both sites, so any pod verifies a link any other made. The token is the
only credential, and carries no file name. Pure; the clock is a parameter."""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

PATH = "/api/files/"


@dataclass(frozen=True)
class Grant:
    """What a valid link lets its holder read: object `household_id`/`sha256`, served as `media_type`, `inline` when
    the page may show it in place and not only save it. `expires_at` is when the link stops (Unix seconds)."""

    household_id: int
    sha256: str
    media_type: str
    inline: bool
    expires_at: int


@dataclass(frozen=True)
class Link:
    url: str
    expires_at: int


def mint(key: bytes, grant: Grant) -> Link:
    """The link to `grant`, a path on this site."""
    payload = _b64(json.dumps({"h": grant.household_id, "s": grant.sha256, "m": grant.media_type,
                               "i": grant.inline, "e": grant.expires_at}, separators=(",", ":")).encode())
    return Link(f"{PATH}{payload}.{_b64(_mac(key, payload))}", grant.expires_at)


def window_end(now: float, ttl_s: int) -> int:
    """When a link minted at `now` stops: the end of the second half-`ttl_s` window after `now`'s own. Every link made
    within one window ends together, so a bench read again within it hands the page the same address, which the
    browser already holds; a link lives between half of `ttl_s` and all of it."""
    half = max(1, ttl_s // 2)
    return (int(now) // half + 2) * half


def check(key: bytes, token: str, now: float) -> Grant | None:
    """The grant `token` carries, None when it is malformed, forged or expired."""
    payload, _, mac = token.partition(".")
    try:
        if not hmac.compare_digest(_b64(_mac(key, payload)), mac):
            return None
        raw = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        grant = Grant(int(raw["h"]), str(raw["s"]), str(raw["m"]), bool(raw["i"]), int(raw["e"]))
    except (ValueError, KeyError, TypeError, binascii.Error):
        return None
    return grant if now < grant.expires_at else None


def _mac(key: bytes, payload: str) -> bytes:
    return hmac.new(key, payload.encode(), hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")
