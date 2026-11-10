"""Contract 13 and 14: what `apply_screen` tells Live, and what a `ScreenChanged` is."""

import json

import pytest
from ashley.live.events import BenchChanged, ScreenChanged, Shown, encode
from ashley.workshop.commands import Remove
from ashley.workshop.model import By
from ashley.workshop.workshop import ScreenNotFound
from contract.conversations_support import run
from sb_support import CONVERSATION, add, changed, env, mv


def test_k13_an_accepted_command_publishes_exactly_one_screen_changed_with_its_seq(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            first = await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, 1, 3))
            assert changed(e.live) == [ScreenChanged(Shown(w.home, None), w.tablet, first.seq)]
            second = await e.workshop.apply_screen(w.home, w.tablet, mv(w.sam, 2, 0))
            assert changed(e.live)[1:] == [ScreenChanged(Shown(w.home, None), w.tablet, second.seq)]
            assert second.seq == first.seq + 1 and len(changed(e.live)) == 2
            assert not [x for x in e.live.published if isinstance(x, BenchChanged)]

    run(scenario())


def test_k13_a_refusal_on_an_existing_bench_publishes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, 1, 3))
            seen = len(e.live.published)
            for refused in (add(w.alana, "clock"), mv(w.alana, 1, 9), Remove(By(w.alana.person_id), CONVERSATION)):
                got = await e.workshop.apply_screen(w.home, w.tablet, refused)
                assert got.outcome != "accepted"
            assert len(e.live.published) == seen

    run(scenario())


def test_k13_creation_publishes_even_when_its_command_is_refused_and_only_once_when_it_is_accepted(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            refused = await e.workshop.apply_screen(w.home, w.tablet, Remove(By(w.alana.person_id), CONVERSATION))
            assert refused.outcome == "required"
            assert changed(e.live) == [ScreenChanged(Shown(w.home, None), w.tablet, refused.seq)]
            accepted = await e.workshop.apply_screen(w.home, w.kitchen, mv(w.alana, 1, 2))
            assert changed(e.live)[1:] == [ScreenChanged(Shown(w.home, None), w.kitchen, accepted.seq)]

    run(scenario())


def test_k13_a_call_that_raises_publishes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            for device in (w.theirs, w.revoked):
                with pytest.raises(ScreenNotFound):
                    await e.workshop.apply_screen(w.home, device, mv(w.alana, 1, 0))
            assert e.live.published == []

    run(scenario())


@pytest.mark.parametrize("shown", [Shown(1, 5), Shown(1, None, 3), Shown(1, 5, None)])
def test_k14_a_screen_changed_shown_to_a_person_or_a_device_is_refused(shown: Shown) -> None:
    with pytest.raises(ValueError):
        ScreenChanged(shown, 3, 1)


def test_k14_a_household_wide_screen_changed_encodes_as_type_screen() -> None:
    event = ScreenChanged(Shown(4, None), 9, 12)
    wire = json.loads(encode(event))
    assert wire["type"] == "screen" and wire["household_id"] == 4 and wire["person_id"] is None
    assert (event.device_id, event.seq) == (9, 12)
