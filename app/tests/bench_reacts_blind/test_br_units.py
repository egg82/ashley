"""The reaction's pure parts: `wait_s`, the turn built from an `Unseen`, and the shipped configuration."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ashley.channels.wake import bench_react_config
from ashley.channels.wake.bench_react_config import CONFIG
from ashley.channels.wake.bench_react_turn import inbound
from ashley.channels.wake.bench_reacts import wait_s
from ashley.workshop.reactions import Done, Unseen
from bench_reacts_blind_support import SENTINEL

CAP, WINDOW = CONFIG.max_reactions, CONFIG.window_s
ZONE = ZoneInfo("America/Denver")
LAST = datetime(2026, 11, 1, 12, 5, tzinfo=UTC)


def unseen(to_seq: int = 7, count: int = 2, bench: int = 5) -> Unseen:
    done = (Done(to_seq - 1, "add", 11, "document", LAST - timedelta(hours=2)), Done(to_seq, "edit", 11, "document", LAST))
    return Unseen(bench, 3, 9, to_seq - count, to_seq, count, done)


def test_below_the_cap_there_is_no_wait() -> None:
    assert wait_s(()) == 0
    assert wait_s(tuple(100.0 * (n + 1) for n in range(CAP - 1))) == 0


def test_at_the_cap_the_wait_is_until_the_oldest_leaves_the_window() -> None:
    ages = tuple(100.0 * (n + 1) for n in range(CAP))
    assert wait_s(ages) == WINDOW - ages[-1]
    assert wait_s(tuple(a + 50 for a in ages)) == WINDOW - ages[-1] - 50


def test_the_wait_is_positive_while_capped() -> None:
    assert wait_s((1.0,) * CAP) > 0


def test_the_shipped_pause_and_cap_are_the_documented_ones_and_come_from_the_json() -> None:
    raw = json.loads(bench_react_config.FILE.read_text())
    assert (raw["pause_s"], raw["max_reactions"], raw["window_s"]) == (30, 3, 900)
    assert bench_react_config.load() == CONFIG
    assert {"pause_s", "max_reactions", "window_s", "scan", "batch", "listed", "keep_s"} <= set(raw)
    assert all(raw[k] > 0 for k in raw)


def test_the_turn_is_unprompted_on_the_bench_thread_for_its_household_and_owner() -> None:
    got = inbound(unseen(), ZONE)
    assert got.household_id == 3 and got.thread == "bench:5" and got.speaker_id == 9
    assert got.unprompted is True and got.author == "household" and got.bench_id == 5


def test_the_source_is_the_bench_and_the_last_command_handed() -> None:
    assert inbound(unseen(to_seq=7), ZONE).source == "bench_react:5:7"
    assert inbound(unseen(to_seq=8), ZONE).source == "bench_react:5:8"
    assert inbound(unseen(bench=6), ZONE).source == "bench_react:6:7"
    assert inbound(unseen(count=3), ZONE).source == inbound(unseen(count=2), ZONE).source


def test_the_message_lists_the_commands_by_number_type_and_kind_and_the_count_of_all() -> None:
    got = inbound(unseen(to_seq=7, count=4), ZONE)
    assert "#6 add document 11" in got.text and "#7 edit document 11" in got.text
    assert "4" in got.text and SENTINEL not in got.text


def test_each_listed_command_carries_when_it_was_decided_in_the_zone_given() -> None:
    got = inbound(unseen(to_seq=7), ZONE)
    assert "#6 add document 11 (Sun 1 Nov 2026 03:05)" in got.text
    assert "#7 edit document 11 (Sun 1 Nov 2026 05:05)" in got.text


def test_what_she_is_told_to_do_is_the_note_not_the_stored_message() -> None:
    got = inbound(unseen(), ZONE)
    assert got.note and got.note not in got.text


def test_over_the_cap_the_wait_is_until_fewer_than_the_cap_remain() -> None:
    ages = (100.0, 200.0, 300.0, 800.0)[: CAP + 1] if CAP == 3 else tuple(100.0 * (n + 1) for n in range(CAP + 1))
    assert wait_s(ages) == WINDOW - ages[CAP - 1]
