"""The one authenticated read a model provider's connection kind makes before a pasted key is stored
(`ashley.inference.kinds` names the URL per provider)."""

import httpx2

from ..connections.kinds import Refusal

TIMEOUT_S = 10.0


async def answered(http: httpx2.AsyncClient, url: str, headers: dict[str, str]) -> Refusal | None:
    """GET `url` with `headers` (which carry the key) through `http`, following no redirect, giving up after
    `TIMEOUT_S`: None when it answers 2xx with a JSON object; `key_refused` for 400, 401 or 403 (Gemini answers a bad
    key 400); `wrong_service` for a 2xx that is not a JSON object; `unreachable` for any other status, a redirect, or
    no answer in time. Never raises, and never puts the key or the body in a log or an exception."""
    try:
        response = await http.get(url, headers=headers, timeout=TIMEOUT_S, follow_redirects=False)
    except httpx2.HTTPError:
        return "unreachable"
    if response.status_code in (400, 401, 403):
        return "key_refused"
    if not response.is_success:
        return "unreachable"
    try:
        body = response.json()
    except ValueError:
        return "wrong_service"
    return None if isinstance(body, dict) else "wrong_service"
