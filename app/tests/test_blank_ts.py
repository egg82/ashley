"""`blank_ts`: a log-leak check searches the output without each line's own timestamp, and nothing else is hidden."""

import logging
from datetime import UTC, datetime

from ashley import logs
from contract.conversations_support import blank_ts

AT = datetime(2026, 11, 21, 9, 0, 39, 730000, tzinfo=UTC)


def line(**fields: object) -> str:
    record = logging.makeLogRecord({"name": "ashley.test", "levelname": "INFO", "msg": "tools.call", "fields": fields,
                                    "created": AT.timestamp(), "msecs": 730.0})
    return logs.Logfmt().format(record)


def test_a_value_shaped_like_a_clock_matches_the_timestamp_until_it_is_blanked() -> None:
    out = line(tool="remind")
    assert out.startswith("ts=2026-11-21T09:00:39.730Z "), "control: the real formatter wrote this timestamp"
    for value in ("T09:00", "39.73", "2026-11-21", "730"):
        assert value in out, f"control: {value} is inside the timestamp"
        assert value not in blank_ts(out)


def test_the_same_value_in_any_other_field_is_still_found() -> None:
    out = line(tool="remind", query="39.73", at="T09:00")
    assert "39.73" in blank_ts(out) and "T09:00" in blank_ts(out)
    assert blank_ts(out).startswith("ts= level=info ")


def test_every_line_is_blanked_and_a_value_that_merely_contains_ts_is_kept() -> None:
    out = line(a="1") + "\n" + line(note="ts=2026-11-21T09:00:39.730Z")
    first, second = blank_ts(out).splitlines()
    assert first.startswith("ts= ") and second.startswith("ts= ")
    assert 'note="ts=2026-11-21T09:00:39.730Z"' in second
