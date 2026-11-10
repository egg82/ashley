"""The address a connection is reached at, as a person types it."""

import re
from urllib.parse import urlsplit

PIN = re.compile(r"sha256=([0-9a-fA-F]{64})")


def base_url(text: str, schemes: frozenset[str], pinned: bool = False) -> str | None:
    """`text` as a base URL (`https://money.example`, a path allowed for an app served under one, no trailing slash),
    or None when its scheme is not one of `schemes`, it has no host, or it carries credentials, a query, a fragment or
    a port out of range. A `pinned` address must end in the fragment `#sha256=<64 hex digits>`, the fingerprint of
    the certificate the service is reached with, which comes back in lowercase; any other address has no fragment."""
    if pinned:
        base, _, pin = text.strip().partition("#")
        match = PIN.fullmatch(pin)
        found = base_url(base, schemes) if match else None
        return None if found is None or match is None else f"{found}#sha256={match[1].lower()}"
    try:
        parts = urlsplit(text.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in schemes or not parts.hostname or parts.username or parts.password or parts.query \
            or parts.fragment or (port is not None and not 0 < port < 65536):
        return None
    return text.strip().rstrip("/")
