"""`watch`'s result is outside text exactly when the watch kind's `outside` in `watches.json` says so."""

from dataclasses import replace

import pytest
from ashley.watches.config import CONFIG
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from test_watch_tools import call, world

SESSION: dict[str, object] = {"kind": "claude_session", "target": "s1"}


def test_a_kind_that_reads_no_outside_text_leaves_the_result_untainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await call(w.tools(), "watch", SESSION)
            assert not got.is_error and got.outside is False
    run(go())


def test_a_kind_marked_outside_taints_the_result(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CONFIG.kinds, "claude_session", replace(CONFIG.kinds["claude_session"], outside=True))

    async def go() -> None:
        async with world(db_url) as w:
            got = await call(w.tools(), "watch", SESSION)
            assert not got.is_error and got.outside is True
    run(go())
