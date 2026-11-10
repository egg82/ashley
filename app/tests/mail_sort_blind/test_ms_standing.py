"""A standing watch's end moves forward by its `hours` on every successful read, so it ends only when disarmed or after its
source has failed for `hours`; a watch that is not standing still always ends (design: "The sort is a standing watch")."""

from typing import Any

import pytest
from ashley.watches.model import ReadFailed
from mail_sort_blind_support import ADDRESS, ITEMS, KIND, MORE, Store, scenario

SLACK_H = 0.1


def near(got: float, want: float) -> bool:
    return abs(got - want) <= SLACK_H


@pytest.mark.parametrize(("hours", "baseline", "read"),
                         [(6.0, ITEMS, ITEMS), (48.0, ITEMS, ITEMS), (6.0, ITEMS, MORE), (48.0, None, ITEMS)],
                         ids=["quiet-6", "quiet-48", "woke-6", "baseline-48"])
def test_a_successful_read_moves_a_standing_watchs_end_forward_by_its_hours(db_url: str, hours: float,
                                                                           baseline: Any, read: Any) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=hours, standing=True, baseline=baseline)
        s.age(a, hours - 1)
        assert near(s.hours_left(a), 1.0)
        await s.tick(read)
        assert near(s.hours_left(a), hours), s.hours_left(a)

    scenario(db_url, body)


@pytest.mark.parametrize(("hours", "baseline", "read"), [(6.0, ITEMS, ITEMS), (6.0, ITEMS, MORE), (6.0, None, ITEMS)],
                         ids=["quiet", "woke", "baseline"])
def test_a_watch_that_is_not_standing_keeps_the_end_it_was_armed_with(db_url: str, hours: float, baseline: Any,
                                                                      read: Any) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=hours, standing=False, baseline=baseline)
        s.age(a, hours - 1)
        await s.tick(read)
        assert near(s.hours_left(a), 1.0), s.hours_left(a)

    scenario(db_url, body)


def test_a_standing_watch_whose_mailbox_keeps_answering_outlasts_its_hours(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=10.0, standing=True)
        for _ in range(5):
            s.age(a, 8.0)
            await s.tick(ITEMS)
            assert (s.row(a)["state"], s.row(a)["reason"]) == ("armed", None)
        assert near(s.hours_left(a), 10.0)

    scenario(db_url, body)


def test_a_watch_that_is_not_standing_ends_expired_though_its_mailbox_answers(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=10.0, standing=False)
        s.age(a, 8.0)
        await s.tick(ITEMS)
        assert s.row(a)["state"] == "armed"
        s.age(a, 8.0)
        await s.tick(ITEMS)
        assert (s.row(a)["state"], s.row(a)["reason"]) == ("ended", "expired")

    scenario(db_url, body)


def test_a_failed_read_does_not_move_a_standing_watchs_end(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True)
        s.age(a, 5.0)
        await s.tick(ReadFailed("unreachable"))
        assert near(s.hours_left(a), 1.0), s.hours_left(a)

    scenario(db_url, body)


def test_a_standing_watch_ends_once_its_source_has_failed_for_its_hours(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True)
        s.age(a, 3.0)
        for _ in range(4):
            await s.tick(ReadFailed("unreachable"))
            s.due(a)
        assert s.row(a)["state"] in ("armed", "paused")
        s.age(a, 4.0)
        await s.tick(ReadFailed("unreachable"))
        assert (s.row(a)["state"], s.row(a)["reason"]) == ("ended", "expired")

    scenario(db_url, body)


def test_a_standing_watch_whose_source_failed_but_then_answered_lives_on_from_that_read(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True)
        s.age(a, 5.0)
        await s.tick(ReadFailed("unreachable"))
        s.due(a)
        await s.tick(ITEMS)
        assert near(s.hours_left(a), 6.0), s.hours_left(a)
        assert s.row(a)["state"] == "armed"

    scenario(db_url, body)


def test_a_standing_watch_ends_when_it_is_disarmed(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True)
        assert await s.store.disarm(s.household_id, s.person_id, KIND, ADDRESS) is True
        assert (s.row(a)["state"], s.row(a)["reason"]) == ("ended", "disarmed")
        s.due(a)
        await s.tick(ITEMS)
        assert s.row(a)["state"] == "ended"

    scenario(db_url, body)



def test_arming_again_with_other_hours_sets_the_hours_the_end_moves_by(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True)
        assert (await s.arm_for(hours=48.0, standing=True)).id == a
        s.age(a, 47.0)
        await s.tick(ITEMS)
        assert near(s.hours_left(a), 48.0), s.hours_left(a)

    scenario(db_url, body)
