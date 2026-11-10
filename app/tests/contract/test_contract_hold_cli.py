"""`python -m ashley.referee hold|release|status`: duration parsing and the exit status and output of `run`."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from ashley.referee.__main__ import DEFAULT, USAGE, parse_duration, run
from ashley.referee.hold import EtcdHold
from etcd import etcd_url
from lease_support import delete
from lease_support import run as run_async
from lease_support import unique_name

DEAD = "http://127.0.0.1:1"


@pytest.fixture
def hold() -> Generator[EtcdHold]:
    key = f"/ashley-test/hold-cli/{unique_name()}"
    yield EtcdHold(etcd_url(), key=key)
    delete(key)


def command(hold: EtcdHold, *argv: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """Run one command; its exit status and everything it printed."""
    capsys.readouterr()
    code = run_async_value(hold, list(argv))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def run_async_value(hold: EtcdHold, argv: list[str]) -> int:
    result: list[int] = []

    async def scenario() -> None:
        result.append(await run(hold, argv))

    run_async(scenario())
    return result[0]


def expiry(hold: EtcdHold) -> datetime | None:
    found: list[datetime | None] = []

    async def scenario() -> None:
        found.append(await hold.until())

    run_async(scenario())
    return found[0]


# --- parse_duration --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("1m", timedelta(minutes=1)),
    ("30m", timedelta(minutes=30)),
    ("90m", timedelta(minutes=90)),
    ("1h", timedelta(hours=1)),
    ("4h", timedelta(hours=4)),
    ("36h", timedelta(hours=36)),
    ("1d", timedelta(days=1)),
    ("2d", timedelta(days=2)),
    ("10d", timedelta(days=10)),
])
def test_a_number_and_a_unit_parse(text: str, expected: timedelta) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", [
    "", "0m", "0h", "0d", "00m", "30", "m", "h", "d", "h4", "4 h", " 4h", "4h ", "1.5h", "-5m", "+5m", "30s", "4w",
    "4hh", "1d2h", "4h30m", "abc", "four hours", "1e2m",
])
def test_anything_else_is_none(text: str) -> None:
    assert parse_duration(text) is None


# --- hold ------------------------------------------------------------------------------------------------------------

def test_hold_with_a_duration_sets_it_and_exits_zero(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = command(hold, "hold", "30m", capsys=capsys)
    assert code == 0 and out.strip()
    until = expiry(hold)
    assert until is not None
    assert abs((until - datetime.now(UTC) - timedelta(minutes=30)).total_seconds()) < 10


@pytest.mark.parametrize("text, expected", [("2h", timedelta(hours=2)), ("1d", timedelta(days=1))])
def test_each_unit_reaches_the_expiry(
    hold: EtcdHold, capsys: pytest.CaptureFixture[str], text: str, expected: timedelta
) -> None:
    assert command(hold, "hold", text, capsys=capsys)[0] == 0
    until = expiry(hold)
    assert until is not None
    assert abs((until - datetime.now(UTC) - expected).total_seconds()) < 10


def test_hold_with_no_duration_holds_for_the_default(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = command(hold, "hold", capsys=capsys)
    assert code == 0
    until = expiry(hold)
    assert until is not None
    assert abs((until - datetime.now(UTC) - DEFAULT).total_seconds()) < 10


def test_hold_again_replaces_the_expiry(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    command(hold, "hold", "2d", capsys=capsys)
    assert command(hold, "hold", "15m", capsys=capsys)[0] == 0
    until = expiry(hold)
    assert until is not None
    assert abs((until - datetime.now(UTC) - timedelta(minutes=15)).total_seconds()) < 10


# --- release ---------------------------------------------------------------------------------------------------------

def test_release_clears_the_hold_and_exits_zero(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    command(hold, "hold", "1h", capsys=capsys)
    code, out = command(hold, "release", capsys=capsys)
    assert code == 0 and out.strip()
    assert expiry(hold) is None


def test_releasing_when_nothing_is_held_still_exits_zero(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = command(hold, "release", capsys=capsys)
    assert code == 0 and out.strip()


def test_release_tells_a_real_release_from_a_no_op(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    command(hold, "hold", "1h", capsys=capsys)
    real = command(hold, "release", capsys=capsys)[1]
    noop = command(hold, "release", capsys=capsys)[1]
    assert real != noop


# --- status ----------------------------------------------------------------------------------------------------------

def test_status_exits_zero_whether_or_not_there_is_a_hold(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    free_code, free_out = command(hold, "status", capsys=capsys)
    command(hold, "hold", "1h", capsys=capsys)
    held_code, held_out = command(hold, "status", capsys=capsys)
    assert (free_code, held_code) == (0, 0)
    assert free_out.strip() and held_out.strip()
    assert free_out != held_out


def test_status_does_not_change_anything(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    command(hold, "hold", "1h", capsys=capsys)
    before = expiry(hold)
    command(hold, "status", capsys=capsys)
    assert expiry(hold) == before
    release_out = command(hold, "release", capsys=capsys)[0]
    assert release_out == 0
    command(hold, "status", capsys=capsys)
    assert expiry(hold) is None


# --- usage -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    [],
    ["bogus"],
    ["hold", "soon"],
    ["hold", "0m"],
    ["hold", "30"],
    ["hold", "4h", "extra"],
    ["release", "now"],
    ["status", "all"],
    ["Hold"],
])
def test_a_malformed_command_exits_two_prints_usage_and_changes_nothing(
    hold: EtcdHold, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, out = command(hold, *argv, capsys=capsys)
    assert code == 2
    assert USAGE in out
    assert expiry(hold) is None


def test_a_malformed_hold_leaves_an_existing_hold_alone(hold: EtcdHold, capsys: pytest.CaptureFixture[str]) -> None:
    command(hold, "hold", "1h", capsys=capsys)
    before = expiry(hold)
    assert command(hold, "hold", "soon", capsys=capsys)[0] == 2
    assert expiry(hold) == before


# --- unreachable etcd ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [["hold"], ["hold", "30m"], ["release"], ["status"]])
def test_an_unreachable_etcd_exits_one_and_says_something(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, out = command(EtcdHold(DEAD, timeout=1.0), *argv, capsys=capsys)
    assert code == 1
    assert out.strip()


def test_the_default_is_the_documented_four_hours() -> None:
    """Directed at a surviving mutant: the test above follows `DEFAULT`, whatever it is; the docstring says 4h."""
    assert DEFAULT == timedelta(hours=4)
