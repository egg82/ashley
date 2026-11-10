"""Sign-in's settings and policy: OIDC is all three keys and a public URL or nothing, the callback is the public URL's,
and `signin.json` refuses a missing, unknown or nonsensical value."""

from typing import Any

import pytest
from ashley import services, wiring
from ashley.settings import Settings, from_env
from ashley.signin import policy
from ashley.signin.authentik import AuthentikOidc
from ashley.signin.oidc import NullOidc, Oidc

OIDC = {"DATABASE_URL": "postgresql://x/y", "OIDC_ISSUER": "https://auth.test/application/o/ashley/",
        "OIDC_CLIENT_ID": "id", "OIDC_CLIENT_SECRET": "secret", "PUBLIC_URL": "https://ashley.test/"}


@pytest.mark.parametrize("missing", ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "PUBLIC_URL"])
def test_oidc_is_all_or_nothing(missing: str) -> None:
    with pytest.raises(ValueError):
        from_env({k: v for k, v in OIDC.items() if k != missing})


def test_configured_oidc_is_wired_with_the_public_callback() -> None:
    wiring.wire(from_env(OIDC))
    oidc = services.get(Oidc)
    assert isinstance(oidc, AuthentikOidc)
    assert oidc.client.redirect_uri == "https://ashley.test/api/auth/callback"


def test_unconfigured_oidc_is_the_null_object() -> None:
    wiring.wire(Settings(database_url="postgresql://x/y", build_version="t"))
    assert isinstance(services.get(Oidc), NullOidc)


def test_the_shipped_policy_loads() -> None:
    loaded = policy.load()
    assert loaded.idle_days <= loaded.session_days


@pytest.mark.parametrize("change", [
    {"session_days": None}, {"extra": 1}, {"idle_days": 40}, {"touch_minutes": 0}, {"max_pending": True},
    {"pending_minutes": 1.5}, {"touch_minutes": 7 * 1440}])
def test_a_bad_policy_is_refused(change: dict[str, Any]) -> None:
    raw: dict[str, Any] = {"session_days": 30, "idle_days": 7, "touch_minutes": 10, "pending_minutes": 10,
                           "max_pending": 1000, "unmapped_retention_days": 30}
    assert policy.parse(raw) is not None
    raw.update(change)
    raw = {k: v for k, v in raw.items() if v is not None}
    with pytest.raises(ValueError):
        policy.parse(raw)
