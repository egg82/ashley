"""Whether a site's answer lets a page at our origin frame it: from the status and the headers, never the body."""

import pytest

from ashley.tools.frame_policy import frameable
from ashley.tools.page_fetch import Reply

US = "https://ashley.example.com"


def reply(status: int = 200, **headers: str) -> Reply:
    return Reply(status, {name.replace("_", "-"): value for name, value in headers.items()})


@pytest.mark.parametrize("answer,origin,expected", [
    (reply(), US, True),
    (reply(x_frame_options="DENY"), US, False),
    (reply(x_frame_options="deny"), US, False),
    (reply(x_frame_options="SAMEORIGIN"), US, False),
    (reply(x_frame_options=" sameorigin "), US, False),
    (reply(x_frame_options="SAMEORIGIN, SAMEORIGIN"), US, False),
    (reply(x_frame_options="ALLOW-FROM https://ashley.example.com"), US, True),
    (reply(403, x_frame_options="SAMEORIGIN"), US, False),
    (reply(403), US, False),
    (reply(404), US, False),
    (reply(503), US, False),
    (reply(301), US, False),
    (reply(content_security_policy="frame-ancestors 'none'"), US, False),
    (reply(content_security_policy="frame-ancestors 'self'"), US, False),
    (reply(content_security_policy="frame-ancestors"), US, False),
    (reply(content_security_policy="frame-ancestors https://other.example"), US, False),
    (reply(content_security_policy="frame-ancestors https://ashley.example.com"), US, True),
    (reply(content_security_policy="frame-ancestors https://ashley.example.com:443"), US, True),
    (reply(content_security_policy="frame-ancestors https://ashley.example.com:8443"), US, False),
    (reply(content_security_policy="frame-ancestors ashley.example.com"), US, True),
    (reply(content_security_policy="Frame-Ancestors 'self' HTTPS://ASHLEY.EXAMPLE.COM"), US, True),
    (reply(content_security_policy="frame-ancestors 'self' https://*.example.com"), US, True),
    (reply(content_security_policy="frame-ancestors https://*.other.example"), US, False),
    (reply(content_security_policy="frame-ancestors *"), US, True),
    (reply(content_security_policy="frame-ancestors https:"), US, True),
    (reply(content_security_policy="frame-ancestors http:"), US, False),
    (reply(content_security_policy="default-src 'self'; frame-ancestors https://ashley.example.com; img-src *"), US, True),
    (reply(content_security_policy="default-src 'none'; img-src *"), US, True),
    (reply(content_security_policy="default-src 'self'", x_frame_options="DENY"), US, False),
    (reply(content_security_policy="frame-ancestors https://ashley.example.com", x_frame_options="SAMEORIGIN"), US, True),
    (reply(content_security_policy="frame-ancestors *, frame-ancestors 'none'"), US, False),
    (reply(content_security_policy="frame-ancestors https://ashley.example.com, script-src 'self'"), US, True),
    (reply(content_security_policy="frame-ancestors https://ashley.example.com"), "", False),
    (reply(content_security_policy="frame-ancestors *"), "", True),
    (reply(content_security_policy="frame-ancestors 'self'"), "https://ashley.test", False),
], ids=lambda value: str(value)[:60])
def test_the_status_and_headers_decide_whether_we_may_frame_it(answer: Reply, origin: str, expected: bool) -> None:
    assert frameable(answer, origin) is expected
