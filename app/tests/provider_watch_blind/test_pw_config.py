"""The watch's tunables: `watch.load` reads the shipped data, `watch.parse` refuses what the docstring lists."""

import pytest
from ashley.inference import watch
from provider_watch_blind_support import CONFIG_DATA, config, without


def test_the_shipped_tunables_are_a_minute_a_ten_minute_window_five_calls_and_half() -> None:
    shipped = watch.load()
    assert (shipped.interval_s, shipped.window_s, shipped.min_calls, shipped.error_share) == (60, 600, 5, 0.5)


def test_the_shipped_tunables_watch_chat_and_count_every_failure_outcome() -> None:
    shipped = watch.load()
    assert shipped.tasks == ("chat",)
    assert set(shipped.failing) == {"error", "unavailable", "invalid_output"}


def test_parse_keeps_what_it_is_given() -> None:
    parsed = watch.parse({"interval_s": 7.5, "window_s": 90, "min_calls": 3, "error_share": 0.25,
                          "failing": ["error"], "tasks": ["chat", "command"]})
    assert (parsed.interval_s, parsed.window_s, parsed.min_calls, parsed.error_share) == (7.5, 90, 3, 0.25)
    assert parsed.failing == ("error",)
    assert set(parsed.tasks) == {"chat", "command"}


@pytest.mark.parametrize("key", sorted(CONFIG_DATA))
def test_a_missing_key_is_refused(key: str) -> None:
    with pytest.raises(ValueError):
        watch.parse(without(key))


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError):
        watch.parse({**CONFIG_DATA, "cooldown_s": 5})


@pytest.mark.parametrize("key", ["interval_s", "window_s", "min_calls"])
@pytest.mark.parametrize("value", [0, -1])
def test_a_duration_or_count_that_is_not_positive_is_refused(key: str, value: int) -> None:
    with pytest.raises(ValueError):
        watch.parse({**CONFIG_DATA, key: value})


@pytest.mark.parametrize("share", [0, -0.1, 1.01, 2])
def test_a_share_outside_zero_exclusive_to_one_inclusive_is_refused(share: float) -> None:
    with pytest.raises(ValueError):
        watch.parse({**CONFIG_DATA, "error_share": share})


def test_a_share_of_exactly_one_is_accepted() -> None:
    assert config(error_share=1).error_share == 1


@pytest.mark.parametrize("outcome", ["ok", "refused", "bogus"])
def test_an_outcome_that_is_not_a_failure_is_refused(outcome: str) -> None:
    with pytest.raises(ValueError):
        watch.parse({**CONFIG_DATA, "failing": ["error", outcome]})


@pytest.mark.parametrize("task", ["bogus", "embed", "voiceprint"])
def test_a_task_that_is_not_a_text_task_is_refused(task: str) -> None:
    with pytest.raises(ValueError):
        watch.parse({**CONFIG_DATA, "tasks": ["chat", task]})
