"""Arming the sort: `brief` and `standing` are set by `watch`; naming tools that act makes it a proposal agreed with
`arm_reminder` in a later person turn, and a woken turn cannot arm one (design: "The sort is a standing watch")."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley.channels.standing import Standing
from ashley.senses.proposal_payloads import OUTSIDE, REMINDERS
from ashley.tools.outside import Outside
from mail_sort_blind_arming_support import ACTING, arming, body, sort_args, use
from mail_sort_blind_turn_support import CONVERSATION, HELD, HOUSEHOLD, PERSON


def test_a_sort_that_acts_is_only_proposed() -> None:
    async def go() -> None:
        async with arming() as w:
            got = await use(w.watch(), "watch", sort_args())
            assert body(got)["armed"] is False and w.store.armed == []
            assert (await w.proposals.pending(PERSON, CONVERSATION, REMINDERS)) is not None

    asyncio.run(go())


def test_the_person_agreeing_in_a_later_turn_arms_it_with_the_brief_and_the_standing_flag() -> None:
    async def go() -> None:
        async with arming() as w:
            await use(w.watch(10), "watch", sort_args(hours=48))
            assert not (await use(w.reminders(11), "arm_reminder")).is_error
            (arm,) = w.store.armed
            assert (arm.kind, arm.target, arm.person_id, arm.tools) == ("mail_inbox", sort_args()["target"], PERSON, ACTING)
            assert (arm.brief, arm.standing) == ("sort what is in the inbox", True)
            assert abs((arm.expires_at - datetime.now(UTC) - timedelta(hours=48)).total_seconds()) < 120

    asyncio.run(go())


def test_the_proposing_turn_cannot_agree_and_arms_nothing() -> None:
    async def go() -> None:
        async with arming() as w:
            await use(w.watch(10), "watch", sort_args())
            assert (await use(w.reminders(10), "arm_reminder")).is_error
            assert w.store.armed == []

    asyncio.run(go())


def test_a_turn_that_has_read_outside_words_cannot_agree_to_it() -> None:
    async def go() -> None:
        async with arming() as w:
            await use(w.watch(10), "watch", sort_args())
            tainted = Outside(w.reminders(11), Standing(HOUSEHOLD, PERSON, True, False), (CONVERSATION, 11), tainted="watch")
            assert (await use(tainted, "arm_reminder")).is_error
            assert w.store.armed == []
            assert not (await use(w.reminders(12), "arm_reminder")).is_error and len(w.store.armed) == 1

    asyncio.run(go())


def test_a_woken_turn_cannot_arm_a_sort_that_acts_because_that_is_a_change_it_would_hold() -> None:
    async def go() -> None:
        async with arming() as w:
            woken = Outside(w.watch(20), Standing(HOUSEHOLD, PERSON, True, False), (CONVERSATION, 20), tainted="watch")
            got = await use(woken, "watch", sort_args())
            assert not got.is_error and got.content.startswith(HELD)
            assert w.store.armed == [] and (await w.proposals.pending(PERSON, CONVERSATION, REMINDERS)) is None
            assert (await w.proposals.pending(PERSON, CONVERSATION, OUTSIDE)) is not None

    asyncio.run(go())


def test_a_watch_that_only_reads_is_armed_at_once_with_its_brief_and_standing() -> None:
    async def go() -> None:
        async with arming() as w:
            got = await use(w.watch(), "watch", sort_args(tools=["mail_search"]))
            assert body(got).get("armed", True) is not False
            (arm,) = w.store.armed
            assert (arm.brief, arm.standing, arm.tools) == ("sort what is in the inbox", True, ("mail_search",))
            assert w.proposals.proposed == []

    asyncio.run(go())


def test_a_watch_with_no_brief_and_no_standing_is_an_ordinary_one() -> None:
    async def go() -> None:
        async with arming() as w:
            await use(w.watch(), "watch", {"kind": "mail_inbox", "target": sort_args()["target"]})
            (arm,) = w.store.armed
            assert (arm.brief, arm.standing) == (None, False)

    asyncio.run(go())


@pytest.mark.parametrize("bad", [{"standing": "yes"}, {"standing": 1}, {"brief": 5}, {"brief": ["a"]}])
def test_a_malformed_brief_or_standing_is_refused_and_arms_and_proposes_nothing(bad: dict[str, Any]) -> None:
    async def go() -> None:
        async with arming() as w:
            assert not (await use(w.watch(), "watch", sort_args())).is_error
            assert len(w.proposals.proposed) == 1
            got = await use(w.watch(), "watch", sort_args(**bad))
            assert got.is_error and got.content.startswith("bad_arguments"), got.content
            assert w.store.armed == [] and len(w.proposals.proposed) == 1

    asyncio.run(go())
