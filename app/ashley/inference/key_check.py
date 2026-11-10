"""The one authenticated read a model provider's connection kind makes before a pasted key is stored: a list of the
provider's models (Anthropic, OpenAI, Gemini, ElevenLabs), which every key that can make calls may read."""

import httpx2

from ..connections.kinds import Refusal

TIMEOUT_S = 10.0


async def answered(http: httpx2.AsyncClient, url: str, headers: dict[str, str]) -> Refusal | None:
    """GET `url` with `headers` (which carry the key) through `http`, following no redirect, giving up after
    `TIMEOUT_S`: None when it answers 2xx with a JSON object; `key_refused` for 400, 401 or 403 (Gemini answers a bad
    key 400); `wrong_service` for a 2xx that is not a JSON object; `unreachable` for any other status, a redirect, or
    no answer in time. Never raises, and never puts the key or the body in a log or an exception."""
    raise NotImplementedError
