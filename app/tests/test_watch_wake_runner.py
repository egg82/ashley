"""The wakes runner takes up a `watch` wake like any wake: it tells her, settles it `turn`; it is left due while the
turn cannot run and told when it can; it expires at the watches' `wake_max_age_s`; a refusal settles it `failed`; and its
turn's source is the wake id."""

import pytest
from ashley.channels.respond import RespondRefused, RespondUnavailable
from ashley.channels.wake import runner, watch_turn
from ashley.watches.config import CONFIG
from bench_reacts_support import SAYS
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from watch_session_support import Watching, watching


async def stored(w: Watching) -> int:
    """The id of the one wake the session finishing stores."""
    await w.arm("working", 1001)
    w.bridge.state("done", 1002)
    assert (await w.tick())["woke"] == 1
    return int(scalar(w.db_url, "SELECT id FROM wakes WHERE kind = 'watch'"))


def outcome(url: str, wake: int) -> str | None:
    return scalar(url, "SELECT outcome FROM wakes WHERE id = %s", (wake,))


def test_a_watch_wake_is_told_and_settled_and_its_turn_is_the_wake(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            wake = await stored(w)
            w.home.model.script = [SAYS]
            assert await runner.sweep() == 1
            assert outcome(db_url, wake) == "turn"
            sources = scalar(db_url, "SELECT coalesce(json_agg(source), '[]') FROM turns WHERE source IS NOT NULL")
            assert sources == [f"wake:{wake}"]
            assert await runner.sweep() == 0
    run(go())


def test_a_wake_whose_turn_cannot_run_is_left_due_and_told_when_it_can(
        db_url: str, connection_kinds_wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(_: object) -> None:
        raise RespondUnavailable("failover")

    async def go() -> None:
        async with watching(db_url) as w:
            wake = await stored(w)
            with monkeypatch.context() as m:
                m.setattr(watch_turn, "respond", down)
                assert await runner.sweep() == 1 and outcome(db_url, wake) is None
            w.home.model.script = [SAYS]
            assert await runner.sweep() == 1 and outcome(db_url, wake) == "turn"
    run(go())


def test_a_wake_older_than_the_watches_keeping_expires_untold(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            wake = await stored(w)
            scalar(db_url, "WITH u AS (UPDATE wakes SET due_at = now() - make_interval(secs => %s) RETURNING 1) "
                           "SELECT count(*) FROM u", (CONFIG.wake_max_age_s + 60,))
            await runner.sweep()
            assert outcome(db_url, wake) == "expired" and w.home.model.prompts == []
    run(go())


def test_a_wake_inside_the_keeping_is_told_though_a_house_wake_would_have_expired(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            wake = await stored(w)
            scalar(db_url, "WITH u AS (UPDATE wakes SET due_at = now() - interval '1 hour' RETURNING 1) "
                           "SELECT count(*) FROM u")
            w.home.model.script = [SAYS]
            await runner.sweep()
            assert outcome(db_url, wake) == "turn"
    run(go())


def test_a_refusal_settles_the_wake_failed(
        db_url: str, connection_kinds_wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(_: object) -> None:
        raise RespondRefused("no")

    async def go() -> None:
        async with watching(db_url) as w:
            wake = await stored(w)
            monkeypatch.setattr(watch_turn, "respond", refuse)
            await runner.sweep()
            assert outcome(db_url, wake) == "failed"
    run(go())


def test_a_watch_that_paused_is_told_as_paused_with_its_reason(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.down = True
            for _ in range(CONFIG.fail_after):
                await w.tick()
            wake = int(scalar(db_url, "SELECT id FROM wakes WHERE kind = 'watch' AND what = 'paused'"))
            w.home.model.script = [SAYS]
            assert await runner.sweep() == 1 and outcome(db_url, wake) == "turn"
            [text] = scalar(db_url, "SELECT coalesce(json_agg(text), '[]') FROM turns WHERE source = %s",
                            (f"wake:{wake}",))
            assert text == "Watch bridge-capture: paused, unreachable"
    run(go())
