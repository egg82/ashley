"""`watch.breaches` and `Share.failed_share`: which provider and task pairs are in breach of the config."""

import pytest
from ashley.inference import watch
from ashley.inference.outcomes import Share
from provider_watch_blind_support import config


def share(calls: int, failed: int, provider: str = "gemini", task: str = "chat") -> Share:
    return Share(task, provider, calls, failed)


def test_failed_share_is_failed_over_calls() -> None:
    assert share(4, 1).failed_share == 0.25
    assert share(4, 4).failed_share == 1.0
    assert share(7, 0).failed_share == 0.0


@pytest.mark.parametrize(("calls", "failed", "breach"), [
    (5, 3, True), (5, 5, True), (10, 5, True), (6, 3, True),
    (5, 2, False), (10, 4, False), (9, 0, False),
    (4, 4, False), (4, 3, False), (1, 1, False),
])
def test_a_pair_breaches_with_at_least_five_calls_of_which_at_least_half_failed(calls: int, failed: int, breach: bool) -> None:
    seen = share(calls, failed)
    assert watch.breaches([seen], config()) == ([seen] if breach else [])


def test_the_thresholds_come_from_the_config() -> None:
    seen = [share(2, 1), share(3, 3), share(10, 9)]
    assert watch.breaches(seen, config(min_calls=2, error_share=0.5)) == seen
    assert watch.breaches(seen, config(min_calls=3, error_share=0.5)) == seen[1:]
    assert watch.breaches(seen, config(min_calls=2, error_share=0.95)) == [seen[1]]
    assert watch.breaches(seen, config(min_calls=2, error_share=1.0)) == [seen[1]]


def test_each_pair_is_judged_on_its_own_counts() -> None:
    bad, quiet, small = share(8, 6, "gemini"), share(8, 1, "anthropic"), share(3, 3, "openai")
    assert watch.breaches([quiet, bad, small], config()) == [bad]


def test_no_pairs_is_no_breach() -> None:
    assert watch.breaches([], config()) == []


def test_a_pair_is_kept_as_given() -> None:
    bad = share(5, 5, "gemini", "command")
    assert watch.breaches(iter([bad]), config()) == [bad]
