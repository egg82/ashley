"""`GET /api/spend`: the contract of the response, and how each state of what is left renders: read, failed, unknown, free
and estimated, none of them looking like a measured amount when it is not one."""

import json
import logging
from collections.abc import Generator
from datetime import UTC, datetime
from importlib import resources

import pytest
from ashley import services
from ashley.api.models import ErrorResponse
from ashley.api.person import SESSION_COOKIE
from ashley.api.spend_models import SpendProvider, SpendResponse
from ashley.channels.spend_report import NullSpendReport, SpendReport
from ashley.channels.spend_view import SpendView
from ashley.db.database import Database
from ashley.inference import spend_catalog
from ashley.inference.balance import BalanceFailed, ProviderBalances, Quota
from ashley.inference.balance_reader import SourcedBalances
from ashley.main import create_app
from ashley.people.people import People
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from spend_support import Told, call, signed_in

PUBLIC = "https://ashley.test"
NOW = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)
QUOTA = Quota("characters", 1200, 10000, datetime(2026, 12, 20, tzinfo=UTC))


def with_sources(sources: dict[str, Told], budgets: object = None) -> None:
    catalog = spend_catalog.parse(json.loads(resources.files("ashley.inference").joinpath("providers.json").read_text()),
                                  {"monthly_usd": budgets or {}})
    services.register(ProviderBalances, SourcedBalances(dict(sources), lambda: NOW))
    services.register(SpendReport, SpendView(services.get(Database), lambda: services.get(People),
                                             lambda: services.get(ProviderBalances), catalog, lambda: NOW))


@pytest.fixture
def client(db_url: str) -> Generator[tuple[TestClient, str]]:
    token, _ = signed_in(db_url)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
        yield c, db_url


def provider(body: SpendResponse, name: str) -> SpendProvider:
    return next(p for p in body.providers if p.provider == name)


def get(c: TestClient) -> SpendResponse:
    got = c.get("/api/spend")
    assert got.status_code == 200
    return SpendResponse.model_validate(got.json())


def test_the_response_validates_against_its_model_and_lists_every_paid_provider_with_nothing_spent(
        client: tuple[TestClient, str]) -> None:
    c, _ = client
    with_sources({})
    body = get(c)
    assert [w.name for w in body.windows] == ["today", "week", "month"] and body.zone == "America/Denver"
    paid = [p.provider for p in body.providers]
    assert paid == ["anthropic", "openai", "gemini", "gemini_image", "openai_image", "elevenlabs"]
    first = body.providers[0]
    assert first.usage.month.calls == 0 and first.usage.month.input_tokens is None and first.usage.month.cost_usd is None
    assert first.tasks == [] and first.estimate is None


def test_usage_is_per_provider_and_per_task_and_the_zone_decides_the_month(client: tuple[TestClient, str]) -> None:
    c, url = client
    with_sources({})
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic", "chat", usage=(100, 50), cost="0.25")
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic", "command", usage=(1, 1), cost="0.125")
    call(url, datetime(2026, 11, 1, 5, 59, tzinfo=UTC), "anthropic", "chat", usage=(9, 9), cost="9")   # October, local
    p = provider(get(c), "anthropic")
    assert (p.usage.month.calls, p.usage.month.input_tokens, p.usage.month.output_tokens) == (2, 101, 51)
    assert p.usage.month.cost_usd == 0.375
    assert [(t.task, t.usage.month.calls) for t in p.tasks] == [("chat", 1), ("command", 1)]


def test_a_quota_read_shows_with_when_it_was_read_and_remaining_never_goes_below_zero(
        client: tuple[TestClient, str]) -> None:
    c, _ = client
    with_sources({"elevenlabs": Told(QUOTA)})
    b = provider(get(c), "elevenlabs").balance
    assert (b.state, b.read_at) == ("read", NOW)
    assert b.quota is not None and (b.quota.used, b.quota.limit, b.quota.remaining, b.quota.unit) == (
        1200, 10000, 8800, "characters")
    with_sources({"elevenlabs": Told(Quota("characters", 12000, 10000, None))})
    over = provider(get(c), "elevenlabs").balance.quota
    assert over is not None and over.remaining == 0 and over.resets_at is None


def test_a_failed_read_is_failed_with_no_quota_never_zero(client: tuple[TestClient, str]) -> None:
    c, _ = client
    with_sources({"elevenlabs": Told(failure=BalanceFailed("refused"))})
    b = provider(get(c), "elevenlabs").balance
    assert b.state == "failed" and b.quota is None and b.read_at == NOW


def test_a_provider_with_no_read_is_unknown_and_says_why_with_its_documentation(client: tuple[TestClient, str]) -> None:
    c, _ = client
    with_sources({})
    body = get(c)
    for name in ("anthropic", "openai", "gemini", "gemini_image", "openai_image"):
        b = provider(body, name).balance
        assert b.state == "unknown" and b.quota is None and b.read_at is None and b.why and b.docs_url
    unset = provider(body, "elevenlabs").balance
    assert unset.state == "unknown" and unset.why == "its key is not set here" and unset.docs_url


def test_a_local_provider_with_calls_is_listed_free_and_one_without_is_not_listed(client: tuple[TestClient, str]) -> None:
    c, url = client
    with_sources({})
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "fastembed", "embed", usage=(30, 0), cost="0")
    body = get(c)
    p = provider(body, "fastembed")
    assert (p.kind, p.balance.state, p.usage.today.input_tokens) == ("local", "free", 30)
    assert "wyoming" not in [x.provider for x in body.providers]


def test_a_provider_the_catalog_does_not_name_is_unlisted_and_unknown(client: tuple[TestClient, str]) -> None:
    c, url = client
    with_sources({})
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "newcomer")
    p = provider(get(c), "newcomer")
    assert (p.kind, p.label, p.balance.state) == ("unlisted", "newcomer", "unknown")


def test_a_budget_gives_an_estimate_that_counts_the_calls_it_could_not_price(client: tuple[TestClient, str]) -> None:
    c, url = client
    with_sources({}, {"anthropic": 10})
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic", cost="2.5")
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic", cost=None)
    body = get(c)
    e = provider(body, "anthropic").estimate
    assert e is not None and (e.budget_usd, e.spent_usd, e.remaining_usd, e.unpriced_calls) == (10, 2.5, 7.5, 1)
    assert provider(body, "openai").estimate is None


def test_a_budget_already_spent_is_a_negative_remainder_not_zero(client: tuple[TestClient, str]) -> None:
    c, url = client
    with_sources({}, {"anthropic": 1})
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic", cost="3")
    e = provider(get(c), "anthropic").estimate
    assert e is not None and e.remaining_usd == -2


def test_the_response_carries_no_key_and_the_log_no_amount(client: tuple[TestClient, str],
                                                           caplog: pytest.LogCaptureFixture) -> None:
    c, url = client
    with_sources({"elevenlabs": Told(QUOTA)})
    call(url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic", cost="2.5")
    with caplog.at_level(logging.INFO):
        got = c.get("/api/spend")
    assert "xi-api-key" not in got.text
    lines = [r.getMessage() for r in caplog.records if r.getMessage() in ("spend.report", "balance.read")]
    assert lines == ["balance.read", "spend.report"]
    fields = {r.getMessage(): getattr(r, "fields") for r in caplog.records if r.getMessage() in ("spend.report", "balance.read")}
    assert fields["balance.read"]["provider"] == "elevenlabs" and fields["balance.read"]["outcome"] == "ok"
    assert "ms" in fields["balance.read"] and "2.5" not in caplog.text and "8800" not in caplog.text


def test_without_a_session_it_is_401(client: tuple[TestClient, str]) -> None:
    c, _ = client
    c.cookies.clear()
    got = c.get("/api/spend")
    assert got.status_code == 401 and ErrorResponse.model_validate(got.json()).code == "unauthorized"


def test_when_the_report_is_not_wired_it_is_503(client: tuple[TestClient, str]) -> None:
    c, _ = client
    services.register(SpendReport, NullSpendReport())
    got = c.get("/api/spend")
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"
