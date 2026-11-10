"""Shared setup for the spend page's tests: ledger rows at chosen instants, a signed-in household, and a balance source
that answers as told."""

import hashlib
import secrets
from datetime import datetime

import psycopg
from ashley.inference.balance import BalanceFailed, BalanceSource, Quota
from ashley.people import admin


def call(url: str, at: datetime, provider: str, task: str = "chat", usage: tuple[int, int] | None = (10, 5),
         cost: str | None = "0.5", characters: int = 0) -> None:
    """One ledger row at `at`; `usage` None is a call that reported none (it stores no usage columns)."""
    cols = (None,) * 6 if usage is None else (usage[0], usage[1], 0, 0, 0, characters)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO inference_calls (at, task, provider, model, outcome, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, audio_ms, characters, cost_usd, duration_ms) "
            "VALUES (%s, %s, %s, 'm', 'ok', %s, %s, %s, %s, %s, %s, %s, 1)",
            (at, task, provider, *cols, cost))


def signed_in(url: str, zone: str = "America/Denver") -> tuple[str, int]:
    """A household in `zone` with one person signed in; the session token and the household id."""
    with psycopg.connect(url) as conn:
        hid = admin.add_household(conn, "home", zone)
        pid = admin.add_person(conn, hid, "Alana")
        account = admin.add_account(conn, pid, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, hid))
    return token, hid


class Told(BalanceSource):
    """Answers with `quota`, or fails as `failure` says, counting the reads."""

    def __init__(self, quota: Quota | None = None, failure: BalanceFailed | None = None) -> None:
        self.quota, self.failure, self.reads = quota, failure, 0

    async def read(self) -> Quota:
        self.reads += 1
        if self.failure is not None:
            raise self.failure
        assert self.quota is not None
        return self.quota
