"""`media.json` is read strictly, and the shipped file is a valid one."""

import json

import pytest
from ashley.runs import media_config

SHIPPED: dict[str, object] = json.loads(media_config.FILE.read_text())


def test_the_shipped_config_parses() -> None:
    config = media_config.load()
    assert config.max_frames >= 1 and config.qualities and config.window_s > 0


CHANGES: list[dict[str, object]] = [
    {"cell_width": 0}, {"max_frames": True}, {"whisper_model": ""}, {"poll_s": "1"}, {"extra": 1},
    {"qualities": []}, {"qualities": [0]}, {"qualities": [32]}, {"qualities": ["4"]}, {"qualities": 4},
    {"silence_peak": 40000}, {"work_mib": 160}, {"frames_deadline_s": 30}, {"transcribe_deadline_s": 30},
    {"log_bytes": 1000}]


@pytest.mark.parametrize("change", CHANGES, ids=[str(sorted(c)[0]) + str(list(c.values())[0]) for c in CHANGES])
def test_a_malformed_config_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        media_config.parse({**SHIPPED, **change})


def test_a_missing_key_is_refused() -> None:
    with pytest.raises(ValueError):
        media_config.parse({k: v for k, v in SHIPPED.items() if k != "window_s"})
