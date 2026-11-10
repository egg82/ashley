"""A kept or failed turn on a paged channel (`Inbound.paged`) stores no turn of hers with words code wrote and tells
the page through Live; resumed over a real Postgres in-flight store."""

from collections.abc import Generator

import pytest
from ashley import logs, services
from ashley.channels import resume
from ashley.inference.inference import InferenceCutOff, InferenceRejected, InferenceUnavailable
from ashley.live.events import TurnFailed
from ashley.live.live import Live
from contract.conversations_support import run
from ifb_resume_support import DONE, world
from live_support import FakeLive


@pytest.fixture
def live() -> Generator[FakeLive]:
    fake = FakeLive()
    services.register(Live, fake)
    yield fake
    services.unregister(Live)


def failures(live: FakeLive) -> list[str]:
    return [e.why for e in live.published if isinstance(e, TurnFailed)]


def test_a_kept_turn_on_a_page_says_nothing_and_shows_retrying(db_url: str, live: FakeLive,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [InferenceUnavailable("down")]
            await resume.sweep()
            assert await w.r.hers() == [] and await w.r.rows() == 1
            assert failures(live) == ["retrying"]

    run(go())


def test_a_later_reply_ends_the_retrying_state_with_her_own_words(db_url: str, live: FakeLive) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [InferenceUnavailable("down")]
            await resume.sweep()
            await w.r.expire_all()
            w.model.script = [DONE]
            await resume.sweep()
            assert await w.r.hers() == [DONE.text] and await w.r.rows() == 0
            assert failures(live) == ["retrying"]

    run(go())


def test_a_paged_turn_whose_work_is_gone_shows_unfinished(db_url: str, live: FakeLive) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [InferenceRejected("rejected")]
            await resume.sweep()
            assert await w.r.hers() == [] and await w.r.rows() == 0
            assert failures(live) == ["unfinished"]

    run(go())


def test_a_paged_turn_cut_off_twice_shows_too_big_and_is_not_kept(db_url: str, live: FakeLive) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [InferenceCutOff("cut off"), InferenceCutOff("cut off again")]
            await resume.sweep()
            assert len(w.model.prompts) == 2 and await w.r.hers() == [] and await w.r.rows() == 0
            assert failures(live) == ["too_big"]

    run(go())
