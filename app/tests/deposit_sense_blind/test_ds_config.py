"""The deposit sense's tunables, `ashley/senses/deposits.json`: the lookback stays under the wakes' keeping (a week), or a
pruned reminder could let its deposit fire again."""

import json
from pathlib import Path

import ashley.senses

KEEP_DAYS = 7


def test_the_tunables_are_there_and_the_lookback_is_shorter_than_the_wakes_are_kept() -> None:
    raw = json.loads((Path(ashley.senses.__file__).parent / "deposits.json").read_text())
    assert {"poll_s", "lookback_days", "per_page", "max_pages"} <= set(raw)
    assert all(isinstance(raw[k], int | float) and raw[k] > 0 for k in ("poll_s", "lookback_days", "per_page", "max_pages"))
    assert raw["lookback_days"] < KEEP_DAYS
