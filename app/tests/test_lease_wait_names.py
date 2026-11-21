"""`wait_until` fails naming what it waited for and the last value it saw."""

import asyncio

import pytest
from contract.lease_support import wait_until


def test_a_timed_out_wait_names_its_label_and_the_last_value_seen() -> None:
    with pytest.raises(AssertionError, match=r"after 0\.05s waiting for the third tick; last seen 2"):
        asyncio.run(wait_until(lambda: False, timeout=0.05, what="the third tick", seen=lambda: 2))


def test_an_unlabelled_wait_names_its_call_site_and_the_predicates_own_value() -> None:
    with pytest.raises(AssertionError, match=r"waiting for test_lease_wait_names\.py:\d+; last seen \[\]"):
        asyncio.run(wait_until(lambda: [], timeout=0.05))


def test_a_wait_that_holds_returns() -> None:
    asyncio.run(wait_until(lambda: "x", timeout=0.05))
