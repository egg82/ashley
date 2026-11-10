"""The ledger read behind the spend page: rows land in the right spans across a month boundary and a time zone, and a
missing measurement stays missing."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ashley.db.pool import PoolDatabase
from ashley.inference.spend_tally import Tally, tally
from ashley.inference.spend_windows import windows
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from spend_support import call

NOW = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)   # Nov 30, 20:00 in Denver, already December in UTC


def read(url: str, zone: str = "America/Denver") -> list[Tally]:
    async def scenario() -> list[Tally]:
        database = PoolDatabase(url)
        await database.open()
        try:
            return await tally(database, windows(NOW, ZoneInfo(zone)))
        finally:
            await database.close()

    return asyncio.run(scenario())


def calls_by_window(rows: list[Tally], provider: str) -> dict[str, int]:
    return {t.window: t.calls for t in rows if t.provider == provider}


def test_each_row_counts_in_every_span_that_holds_it_by_the_households_midnights(db_url: str) -> None:
    def at(*parts: int) -> datetime:
        return datetime(*parts, tzinfo=UTC)

    call(db_url, at(2026, 12, 1, 1, 0), "anthropic")    # Nov 30, 18:00 local: today, week, month
    call(db_url, at(2026, 11, 30, 6, 59), "anthropic")  # Nov 29, 23:59 local: week, month
    call(db_url, at(2026, 11, 24, 7, 0), "anthropic")   # Nov 24, 00:00 local: first moment of the week
    call(db_url, at(2026, 11, 24, 6, 59), "anthropic")  # Nov 23, 23:59 local: month only
    call(db_url, at(2026, 11, 1, 6, 0), "anthropic")    # Nov 1, 00:00 local: first moment of the month
    call(db_url, at(2026, 11, 1, 5, 59), "anthropic")   # Oct 31, 23:59 local: no span
    assert calls_by_window(read(db_url), "anthropic") == {"month": 5, "today": 1, "week": 3}


def test_the_same_rows_in_utc_put_the_december_one_alone_in_the_month(db_url: str) -> None:
    call(db_url, datetime(2026, 12, 1, 1, 0, tzinfo=UTC), "anthropic")
    call(db_url, datetime(2026, 11, 30, 6, 59, tzinfo=UTC), "anthropic")
    assert calls_by_window(read(db_url, "UTC"), "anthropic") == {"month": 1, "today": 1, "week": 2}


def test_a_span_with_no_calls_has_no_row_and_a_database_with_none_reads_empty(db_url: str) -> None:
    assert read(db_url) == []
    call(db_url, datetime(2026, 11, 20, tzinfo=UTC), "gemini")
    assert calls_by_window(read(db_url), "gemini") == {"month": 1}


def test_sums_cover_only_the_rows_that_reported_and_say_how_many_did(db_url: str) -> None:
    when = datetime(2026, 12, 1, 1, 0, tzinfo=UTC)
    call(db_url, when, "elevenlabs", "speak", usage=(0, 0), cost=None, characters=120)   # usage, no price
    call(db_url, when, "elevenlabs", "speak", usage=None, cost=None)                      # failed: nothing reported
    call(db_url, when, "openai", usage=(7, 3), cost="0.25")
    call(db_url, when, "openai", usage=(1, 1), cost="0.125")
    call(db_url, when, "wyoming", "transcribe", usage=None, cost=None)
    rows = {(t.provider, t.window): t for t in read(db_url)}
    eleven = rows["elevenlabs", "today"]
    assert (eleven.calls, eleven.metered, eleven.priced) == (2, 1, 0)
    assert eleven.cost_usd is None and eleven.characters == 120
    openai = rows["openai", "today"]
    assert (openai.input_tokens, openai.output_tokens, openai.cost_usd) == (8, 4, Decimal("0.375"))
    nothing = rows["wyoming", "today"]
    assert (nothing.calls, nothing.metered, nothing.input_tokens, nothing.characters, nothing.cost_usd) == (
        1, 0, None, None, None)


def test_tasks_are_separate_rows_of_one_provider(db_url: str) -> None:
    when = datetime(2026, 12, 1, 1, 0, tzinfo=UTC)
    call(db_url, when, "gemini", "chat")
    call(db_url, when, "gemini", "command")
    got = [(t.task, t.window) for t in read(db_url) if t.window == "today"]
    assert got == [("chat", "today"), ("command", "today")]
