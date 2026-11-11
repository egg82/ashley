"""The footer every brief gets, and `idle_nudge_s` as a tunable in `jobs.json`."""

import json
from pathlib import Path
from typing import Any

import pytest

from bench_jobs_finish_blind_support import config
from bjb_support import cfg
from ashley.errands import jobs_config
from ashley.tools import bench_session


def shipped() -> dict[str, Any]:
    data: Any = json.loads(Path(jobs_config.__file__).with_name("jobs.json").read_text())
    assert data
    return data


def test_footer_names_the_result_file_the_out_folder_and_the_configured_limits() -> None:
    text = bench_session.footer(config(max_outputs=3, result_chars=1234))
    for token in ("RESULT.md", "./out", "./in", "3", "1234"):
        assert token in text, token
    assert "800" not in text


def test_footer_follows_the_shipped_limits() -> None:
    text = bench_session.footer()
    assert str(cfg().max_outputs) in text and str(cfg().result_chars) in text and "RESULT.md" in text


def test_config_idle_nudge_s_is_shipped_and_positive() -> None:
    assert cfg().idle_nudge_s > 0
    assert shipped()["idle_nudge_s"] == cfg().idle_nudge_s


def test_config_a_positive_idle_nudge_s_is_loaded_as_given() -> None:
    assert jobs_config.parse({**shipped(), "idle_nudge_s": 42}).idle_nudge_s == 42
    assert jobs_config.parse({**shipped(), "idle_nudge_s": 0.5}).idle_nudge_s == 0.5


def test_config_a_missing_idle_nudge_s_is_refused_at_load() -> None:
    data = shipped()
    del data["idle_nudge_s"]
    with pytest.raises(ValueError):
        jobs_config.parse(data)


@pytest.mark.parametrize("bad", [0, 0.0, -1, -0.5])
def test_config_a_non_positive_idle_nudge_s_is_refused_at_load(bad: float) -> None:
    with pytest.raises(ValueError):
        jobs_config.parse({**shipped(), "idle_nudge_s": bad})
