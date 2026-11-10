"""`ElevenLabsQuota`: the character quota of the account the key belongs to, from `GET /v1/user/subscription` on the
same configured client as `ElevenLabsSpeaker` (`character_count` of `character_limit`, reset at
`next_character_count_reset_unix`). ElevenLabs bills in characters, so this is a quota, not an amount of money."""

from datetime import UTC, datetime

import httpx2

from .balance import BalanceFailed, BalanceSource, Quota


class ElevenLabsQuota(BalanceSource):
    def __init__(self, client: httpx2.AsyncClient, timeout_s: float = 5.0) -> None:
        self._client = client
        self._timeout_s = timeout_s

    async def read(self) -> Quota:
        try:
            response = await self._client.get("/v1/user/subscription", timeout=self._timeout_s)
        except httpx2.HTTPError as e:
            raise BalanceFailed("unreachable") from e
        if response.status_code in (401, 403):
            raise BalanceFailed("refused")
        if response.is_error:
            raise BalanceFailed("http_error")
        try:
            body = response.json()
            used, limit, reset = body["character_count"], body["character_limit"], body.get("next_character_count_reset_unix")
        except (ValueError, KeyError, TypeError) as e:
            raise BalanceFailed("malformed") from e
        if not _count(used) or not _count(limit) or not (reset is None or _count(reset)):
            raise BalanceFailed("malformed")
        try:
            resets_at = None if reset is None else datetime.fromtimestamp(reset, UTC)
        except (OverflowError, OSError, ValueError) as e:
            raise BalanceFailed("malformed") from e
        return Quota("characters", used, limit, resets_at)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
