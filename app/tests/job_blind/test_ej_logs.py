"""Logs: `errands.tick` and one line per errand outcome carry ids, counts and durations, never the ask or the result."""

import pytest
from ashley import logs
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from contract.conversations_support import events
from job_blind_support import (ASK, FIELD_ATTEMPT, FIELD_DURATION, FIELD_ERRAND, FIELD_REASON, FIELD_TOOL_CALLS,
                               SECRETS, TICK_FIELDS, World, owed_again, scenario, use_list)


@pytest.fixture(autouse=True)
def logging_on(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()


def test_a_tick_logs_its_counts(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def body(w: World) -> None:
        await w.owe()
        await w.owe("search")
        w.model.play(owed_again())
        await w.tick()

    scenario(db_url, body)
    [line] = events(capsys.readouterr().out, "errands.tick")
    assert all(f in line for f in TICK_FIELDS)
    assert (line["swept"], line["claimed"], line["done"], line["released"], line["given_up"]) == ("0", "2", "1", "1", "0")
    assert int(line[FIELD_DURATION]) >= 0


def test_an_idle_tick_still_logs_with_zero_counts(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def body(w: World) -> None:
        await w.tick()
        await w.tick()

    scenario(db_url, body)
    lines = events(capsys.readouterr().out, "errands.tick")
    assert len(lines) == 2
    assert all((ln["claimed"], ln["done"], ln["released"], ln["given_up"]) == ("0", "0", "0", "0") for ln in lines)


def test_the_tick_counts_what_the_sweep_gave_up(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    from job_blind_support import CONF, age_created

    async def body(w: World) -> None:
        a, b = await w.owe_many(2)
        age_created(w.url, a, CONF.max_age_s + 10)
        age_created(w.url, b, CONF.max_age_s + 10)
        await w.tick()

    scenario(db_url, body)
    [line] = events(capsys.readouterr().out, "errands.tick")
    assert line["swept"] == "2"


def test_done_line_carries_errand_attempt_tool_calls_and_duration(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    ids: list[int] = []

    async def body(w: World) -> None:
        ids.append(await w.owe())
        w.model.play(use_list())
        await w.tick()

    scenario(db_url, body)
    [line] = events(capsys.readouterr().out, "errands.done")
    assert line[FIELD_ERRAND] == str(ids[0]) and line[FIELD_ATTEMPT] == "1"
    assert line[FIELD_TOOL_CALLS] == "1" and int(line[FIELD_DURATION]) >= 0


def test_released_line_for_owed_again(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    ids: list[int] = []

    async def body(w: World) -> None:
        ids.append(await w.owe())
        w.model.play(owed_again())
        await w.tick()

    scenario(db_url, body)
    out = capsys.readouterr().out
    [line] = events(out, "errands.released")
    assert line[FIELD_ERRAND] == str(ids[0]) and line[FIELD_ATTEMPT] == "1" and FIELD_DURATION in line
    assert events(out, "errands.done") == [] and events(out, "errands.given_up") == []


def test_released_line_for_inference_unavailable(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def body(w: World) -> None:
        await w.owe()
        w.model.play(InferenceUnavailable("down"))
        await w.tick()

    scenario(db_url, body)
    out = capsys.readouterr().out
    assert len(events(out, "errands.released")) == 1
    [tick] = events(out, "errands.tick")
    assert (tick["claimed"], tick["released"], tick["done"]) == ("1", "1", "0")


def test_given_up_line_carries_the_reason(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    ids: list[int] = []

    async def body(w: World) -> None:
        ids.append(await w.owe())
        w.model.play(InferenceRefused("no"))
        await w.tick()

    scenario(db_url, body)
    [line] = events(capsys.readouterr().out, "errands.given_up")
    assert line[FIELD_ERRAND] == str(ids[0]) and line[FIELD_REASON] == "refused" and FIELD_ATTEMPT in line


def test_a_release_that_exhausts_the_attempts_is_logged_as_given_up_or_released_but_counted_once(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    from job_blind_support import CONF, set_attempts

    async def body(w: World) -> None:
        eid = await w.owe()
        set_attempts(w.url, eid, CONF.max_attempts - 1)
        w.model.play(owed_again())
        await w.tick()

    scenario(db_url, body)
    out = capsys.readouterr().out
    [tick] = events(out, "errands.tick")
    assert int(tick["released"]) + int(tick["given_up"]) == 1


def test_no_log_line_carries_the_ask_the_result_or_the_tool_text(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def body(w: World) -> None:
        await w.owe_many(2)
        w.model.play(use_list(), InferenceRefused(ASK))
        await w.tick()
        await w.owe()
        w.model.play(owed_again(), InferenceUnavailable(ASK))
        await w.tick()

    scenario(db_url, body)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "errands.tick" in out
    for secret in SECRETS:
        assert secret not in out
