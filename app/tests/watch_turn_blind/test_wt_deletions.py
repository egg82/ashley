"""What the switch-over deletes: the session sense and its store, config and data file, and the old wake turn no longer
import; their replacements do (so the checks can fail); the singleton that ran the sense is not wired any more."""

from pathlib import Path

import ashley
import pytest
from watch_turn_blind_support import importable

GONE = ("ashley.herdr.watch", "ashley.herdr.watched", "ashley.herdr.postgres_watched", "ashley.herdr.watch_config",
        "ashley.channels.wake.herdr_turn")
STAYS = ("ashley.herdr.bridge", "ashley.herdr.model", "ashley.channels.wake.runner", "ashley.channels.wake.reminder_turn",
         "ashley.channels.wake.wake_turn", "ashley.tools.claude_watching", "ashley.channels.wake.watch_turn")
ROOT = Path(ashley.__file__).parent


@pytest.mark.parametrize("name", GONE)
def test_the_module_no_longer_imports(name: str) -> None:
    assert importable(name) is False


@pytest.mark.parametrize("name", STAYS)
def test_what_stays_or_replaces_it_imports(name: str) -> None:
    assert importable(name) is True


def test_the_poll_settings_file_is_gone_and_its_neighbours_stay() -> None:
    assert not (ROOT / "herdr" / "watch.json").exists()
    assert (ROOT / "herdr" / "herdr.json").exists()


def test_the_replacement_wake_is_in_the_wakes_module() -> None:
    from ashley.senses import wakes

    assert hasattr(wakes, "WatchWake")


def test_nothing_wired_still_names_the_session_sense() -> None:
    text = (ROOT / "wiring_singletons.py").read_text()
    assert "singletons" in text
    assert "herdr.watch" not in text and "herdr_watch" not in text and "WatchUnavailable" not in text


@pytest.mark.parametrize("name", GONE)
def test_wt_the_old_module_file_is_gone_whether_or_not_it_would_import(name: str) -> None:
    assert not (ROOT.parent / (name.replace(".", "/") + ".py")).exists()
