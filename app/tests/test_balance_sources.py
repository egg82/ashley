"""`ElevenLabsQuota` against an in-process server and `SourcedBalances` around a source: how each failure is classified,
that a read is cached and logged once, and that nothing secret is logged. The response bodies are shaped from
ElevenLabs' documented `GET /v1/user/subscription`; none was captured from the live service."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from ashley.inference.balance import BalanceFailed, Quota
from ashley.inference.balance_reader import SourcedBalances
from ashley.inference.elevenlabs_quota import ElevenLabsQuota
from spend_support import Told

GOOD = {"character_count": 1200, "character_limit": 10000, "next_character_count_reset_unix": 1_797_000_000,
        "tier": "creator"}


def source(handler: httpx2.MockTransport) -> tuple[ElevenLabsQuota, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler.handle_request(request)

    client = httpx2.AsyncClient(base_url="https://api.test", headers={"xi-api-key": "k"},
                                transport=httpx2.MockTransport(record))
    return ElevenLabsQuota(client), seen


def answering(status: int, body: object) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda r: httpx2.Response(status, json=body))


def outcome(s: ElevenLabsQuota) -> str:
    with pytest.raises(BalanceFailed) as raised:
        asyncio.run(s.read())
    return raised.value.outcome


def test_it_reads_the_subscription_with_the_key_and_returns_used_limit_and_reset() -> None:
    s, seen = source(answering(200, GOOD))
    quota = asyncio.run(s.read())
    assert (seen[0].method, seen[0].url.path, seen[0].headers["xi-api-key"]) == ("GET", "/v1/user/subscription", "k")
    assert quota == Quota("characters", 1200, 10000, datetime.fromtimestamp(1_797_000_000, UTC))


def test_a_reset_the_provider_does_not_give_is_none() -> None:
    s, _ = source(answering(200, {"character_count": 1, "character_limit": 2, "next_character_count_reset_unix": None}))
    assert asyncio.run(s.read()).resets_at is None


@pytest.mark.parametrize(("status", "expected"), [(401, "refused"), (403, "refused"), (429, "http_error"),
                                                  (500, "http_error")])
def test_an_error_status_is_refused_when_the_key_is_not_accepted_else_http_error(status: int, expected: str) -> None:
    assert outcome(source(answering(status, {"detail": "x"}))[0]) == expected


@pytest.mark.parametrize("body", [{}, [], "text", {"character_count": "12", "character_limit": 5},
                                  {"character_count": True, "character_limit": 5}, {"character_count": -1, "character_limit": 5},
                                  {"character_count": 1, "character_limit": 5, "next_character_count_reset_unix": 10**30}])
def test_a_body_without_a_plain_quota_is_malformed(body: object) -> None:
    assert outcome(source(answering(200, body))[0]) == "malformed"


def test_no_answer_is_unreachable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    assert outcome(source(httpx2.MockTransport(refuse))[0]) == "unreachable"


def test_a_read_is_cached_for_the_ttl_and_taken_again_after_it() -> None:
    told, clock = Told(Quota("characters", 1, 2, None)), [datetime(2026, 12, 1, tzinfo=UTC)]
    balances = SourcedBalances({"elevenlabs": told}, lambda: clock[0], timedelta(seconds=60))

    async def scenario() -> None:
        first = await balances.reading("elevenlabs")
        clock[0] += timedelta(seconds=59)
        assert await balances.reading("elevenlabs") is first
        clock[0] += timedelta(seconds=2)
        later = await balances.reading("elevenlabs")
        assert later is not first and later is not None and later.read_at == clock[0]

    asyncio.run(scenario())
    assert told.reads == 2


def test_a_failed_read_is_cached_too_so_a_down_provider_is_asked_once_a_minute() -> None:
    told = Told(failure=BalanceFailed("unreachable"))
    balances = SourcedBalances({"elevenlabs": told})

    async def scenario() -> None:
        assert (await asyncio.gather(*(balances.reading("elevenlabs") for _ in range(5))))[0] is not None
        reading = await balances.reading("elevenlabs")
        assert reading is not None and reading.quota is None

    asyncio.run(scenario())
    assert told.reads == 1


def test_a_provider_with_no_source_has_no_reading() -> None:
    assert asyncio.run(SourcedBalances({}).reading("anthropic")) is None


def test_each_read_that_reaches_the_provider_logs_its_outcome_and_duration_only(caplog: pytest.LogCaptureFixture) -> None:
    balances = SourcedBalances({"elevenlabs": Told(failure=BalanceFailed("refused"))})
    with caplog.at_level(logging.INFO, logger="ashley.inference"):
        asyncio.run(balances.reading("elevenlabs"))
        asyncio.run(balances.reading("elevenlabs"))
    logged = [r for r in caplog.records if r.getMessage() == "balance.read"]
    assert len(logged) == 1
    fields = getattr(logged[0], "fields")
    assert set(fields) == {"provider", "outcome", "ms"} and fields["outcome"] == "refused"
