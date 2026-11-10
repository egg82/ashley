"""The part of pywebpush that `ashley.channels.push.sender` uses; the package ships no type information."""

from collections.abc import Mapping

import requests
from py_vapid import Vapid01

class WebPushException(Exception):
    response: requests.Response | None
    def __init__(self, message: str, response: object = ...) -> None: ...

def webpush(
    subscription_info: Mapping[str, object],
    data: str | None = ...,
    vapid_private_key: Vapid01 | str | None = ...,
    vapid_claims: dict[str, str | int] | None = ...,
    content_encoding: str = ...,
    curl: bool = ...,
    timeout: float | None = ...,
    ttl: int = ...,
    verbose: bool = ...,
    headers: dict[str, str | int | float] | None = ...,
    requests_session: requests.Session | None = ...,
) -> str | requests.Response: ...
