"""`watch.evaluate`: one pass over the real ledger, what it returns and the lines it logs."""

import logging

import pytest
from ashley import services
from ashley.db.database import DatabaseUnavailable
from ashley.inference import watch
from ashley.inference.outcomes import Share
from ashley.inference.provider import Failure
from provider_watch_blind_support import FAILURES, ALERT, ALERT_FIELDS, PASS, config, fields_of, go, records_of, rig


@pytest.fixture(autouse=True)
def info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)


def test_a_provider_failing_most_of_its_chat_calls_is_returned_and_alerted(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 3)
            await r.add("chat", "gemini", "ok", 2)
            await r.add("chat", "anthropic", "ok", 5)
            return await watch.evaluate(config())

    assert go(scenario()) == [Share("chat", "gemini", 5, 3)]
    [alert] = fields_of(caplog, ALERT)
    assert alert["task"] == "chat"
    assert alert["provider"] == "gemini"
    assert (alert["calls"], alert["failed"], alert["window_s"]) == (5, 3, 600)
    assert alert["share"] == pytest.approx(0.6)


def test_the_alert_is_a_warning_of_ids_and_counts_only(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "invalid_output", 5)
            return await watch.evaluate(config())

    go(scenario())
    [record] = records_of(caplog, ALERT)
    assert record.levelno == logging.WARNING
    fields = dict(getattr(record, "fields", {}))
    assert set(fields) == ALERT_FIELDS
    assert all(isinstance(v, str | int | float) for v in fields.values())


def test_every_evaluation_logs_a_pass_line_with_pairs_and_alerts(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 5)
            await r.add("chat", "anthropic", "ok", 5)
            await watch.evaluate(config())

    go(scenario())
    [line] = fields_of(caplog, PASS)
    assert (line["pairs"], line["alerts"]) == (2, 1)


def test_the_pass_line_carries_the_evaluations_duration_in_milliseconds(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url):
            await watch.evaluate(config())

    go(scenario())
    [line] = fields_of(caplog, PASS)
    duration = line["duration_ms"]
    assert isinstance(duration, int) and duration >= 0


def test_a_quiet_ledger_returns_nothing_and_logs_no_alert(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "ok", 8)
            await r.add("chat", "anthropic", "error", 1)
            return await watch.evaluate(config())

    assert go(scenario()) == []
    assert fields_of(caplog, ALERT) == []
    [line] = fields_of(caplog, PASS)
    assert (line["pairs"], line["alerts"]) == (2, 0)


def test_an_empty_ledger_is_a_pass_of_no_pairs(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url):
            return await watch.evaluate(config())

    assert go(scenario()) == []
    [line] = fields_of(caplog, PASS)
    assert (line["pairs"], line["alerts"]) == (0, 0)


def test_four_failed_calls_are_too_few_to_alert(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 4)
            return await watch.evaluate(config())

    assert go(scenario()) == []
    assert fields_of(caplog, ALERT) == []


def test_refusals_and_answers_are_not_failures(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "refused", 10)
            return await watch.evaluate(config())

    assert go(scenario()) == []
    assert fields_of(caplog, ALERT) == []


@pytest.mark.parametrize("outcome", FAILURES)
def test_each_failure_outcome_counts_toward_an_alert(db_url: str, outcome: Failure) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", outcome, 5)
            return await watch.evaluate(config())

    assert go(scenario()) == [Share("chat", "gemini", 5, 5)]


def test_a_task_the_watch_does_not_cover_is_not_alerted(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("command", "gemini", "error", 20)
            return await watch.evaluate(config())

    assert go(scenario()) == []
    assert fields_of(caplog, ALERT) == []
    assert fields_of(caplog, PASS)[0]["pairs"] == 0


def test_calls_older_than_the_window_do_not_count(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 20, age_s=700)
            return await watch.evaluate(config())

    assert go(scenario()) == []
    assert fields_of(caplog, ALERT) == []


def test_the_tasks_and_window_come_from_the_config(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("command", "gemini", "error", 3)
            await r.add("chat", "gemini", "error", 3)
            await r.add("chat", "anthropic", "error", 3, age_s=100)
            return await watch.evaluate(config(tasks=["command"], min_calls=3, window_s=50))

    assert go(scenario()) == [Share("command", "gemini", 3, 3)]
    [alert] = fields_of(caplog, ALERT)
    assert alert["window_s"] == 50


def test_the_watch_keeps_no_state_so_a_breach_repeats_until_it_clears(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[list[Share]]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 5)
            first = await watch.evaluate(config())
            second = await watch.evaluate(config())
            await r.clear()
            return [first, second, await watch.evaluate(config())]

    first, second, third = go(scenario())
    assert first == second == [Share("chat", "gemini", 5, 5)]
    assert third == []
    assert len(fields_of(caplog, ALERT)) == 2


def test_an_unreachable_ledger_raises_database_unavailable() -> None:
    services.clear()
    with pytest.raises(DatabaseUnavailable):
        go(watch.evaluate(config()))


def test_the_failing_outcomes_come_from_the_config(db_url: str) -> None:
    async def scenario() -> tuple[list[Share], list[Share]]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "unavailable", 5)
            return (await watch.evaluate(config(failing=["error"])),
                    await watch.evaluate(config(failing=["unavailable"])))

    other, own = go(scenario())
    assert other == []
    assert own == [Share("chat", "gemini", 5, 5)]


def test_every_provider_in_breach_is_alerted(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 5)
            await r.add("chat", "anthropic", "unavailable", 6)
            await r.add("chat", "openai", "ok", 6)
            return await watch.evaluate(config())

    assert go(scenario()) == [Share("chat", "anthropic", 6, 6), Share("chat", "gemini", 5, 5)]
    assert {f["provider"] for f in fields_of(caplog, ALERT)} == {"anthropic", "gemini"}


def test_calls_within_the_window_but_older_than_the_interval_count(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 5, age_s=300)
            return await watch.evaluate(config())

    assert go(scenario()) == [Share("chat", "gemini", 5, 5)]
