"""How sign-in names an account it may log: the system it signs in through, and a short hash of the account's id."""

import hashlib

SYSTEM = "oidc"


def sub_prefix(sub: str) -> str:
    """The first 12 hex of the sub's SHA-256: enough for the admin to tell one refused account from another in a log
    line and find it in `python -m ashley.signin unmapped`, never the sub itself."""
    return hashlib.sha256(sub.encode()).hexdigest()[:12]
