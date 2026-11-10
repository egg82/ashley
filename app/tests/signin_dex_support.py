"""The Dex that `ASHLEY_TEST_DEX_URL` names (its issuer URL), with the static client and password user of
`tests/dex/config.yaml`, and the browser's part of a sign-in against it."""

import os
import re
from html import unescape
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx2
import pytest

from ashley.signin.provider import Client

ENV = "ASHLEY_TEST_DEX_URL"
REDIRECT_URI = "https://ashley.test/api/auth/callback"
USERNAME = "alana"
PASSWORD = "password"
EMAIL = "alana@example.test"
USER_ID = "08a8684b-db88-4b73-90a9-3cd1661f5466"
_MAX_HOPS = 8


def dex_issuer() -> str:
    """The Dex to test against. Unset fails under CI (`CI=true`), so these tests cannot silently stop running there;
    locally it skips, with the reason."""
    url = os.environ.get(ENV)
    if url:
        return url
    if os.environ.get("CI") == "true":
        pytest.fail(f"{ENV} is unset under CI: the Dex sign-in tests must run there")
    pytest.skip(f"{ENV} is unset: no Dex to test against (CI sets it)")


def dex_client(issuer: str, secret: str = "ashley-test-secret") -> Client:
    return Client(issuer, "ashley-test", secret, REDIRECT_URI)


def log_in(authorize_url: str, password: str = PASSWORD) -> tuple[str, str]:
    """(code, state) Dex puts on the redirect to `REDIRECT_URI`, after the browser's walk from `authorize_url`: Dex's login
    form submitted with the static user's credentials. The callback itself is not fetched."""
    with httpx2.Client(follow_redirects=False) as browser:
        url, form = authorize_url, None
        for _ in range(_MAX_HOPS):
            response = browser.get(url) if form is None else browser.post(url, data=form)
            if response.is_redirect:
                url, form = urljoin(url, response.headers["location"]), None
                if url.startswith(REDIRECT_URI):
                    query = parse_qs(urlsplit(url).query)
                    return query["code"][0], query["state"][0]
                continue
            action = re.search(r'<form[^>]*action="([^"]*)"', response.text)
            assert action, f"Dex answered {response.status_code} with no form"
            url, form = urljoin(url, unescape(action.group(1))), {"login": EMAIL, "password": password}
    raise AssertionError("Dex never redirected to the callback")
