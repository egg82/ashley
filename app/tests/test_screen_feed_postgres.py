"""A camera's feed on open screens in Postgres (`ashley.live.postgres_screens.PostgresScreens`): it goes only to the
screens of the people and devices named that are open and in the foreground, replaces what they showed, is read back by
the screen's own token for its own owner only, is gone once its time is up (a clock moved by the caller), when the
screen dismisses it, when the household's feeds are cleared, and with the screen when it closes."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ashley.db.pool import PoolDatabase
from ashley.live.postgres_screens import PostgresScreens
from ashley.live.screens import ScreenFeed, Screens
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar
from screen_bench_support import device

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
CAMERA = "camera.zq_porch"


@asynccontextmanager
async def stores(url: str) -> AsyncGenerator[Screens]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresScreens(db)
    finally:
        await db.close()


def test_the_feed_goes_to_the_named_screens_that_are_open_and_in_the_foreground(db_url: str) -> None:
    home = household(db_url)
    ann, bea, cam = person(db_url, home, "Ann"), person(db_url, home, "Bea"), person(db_url, home, "Cam")
    kiosk = device(db_url, home)
    tokens = {name: str(uuid4()) for name in ("ann", "ann_back", "bea", "cam", "kiosk")}

    async def go() -> None:
        async with stores(db_url) as screens:
            await screens.opened(home, ann, tokens["ann"])
            await screens.opened(home, ann, tokens["ann_back"])
            await screens.opened(home, bea, tokens["bea"])
            await screens.opened(home, cam, tokens["cam"])
            await screens.device_opened(home, kiosk, tokens["kiosk"])
            await screens.person_visible(ann, tokens["ann"], True)
            await screens.person_visible(ann, tokens["ann_back"], False)
            await screens.device_visible(kiosk, tokens["kiosk"], True)
            await screens.person_visible(cam, tokens["cam"], True)
            until = NOW + timedelta(seconds=90)
            assert await screens.show_feed(home, CAMERA, until, (ann, bea), (kiosk,), 60) == 2
            assert await screens.feed_of(tokens["ann"], NOW, person_id=ann) == ScreenFeed(CAMERA, until)
            assert await screens.feed_of(tokens["kiosk"], NOW, device_id=kiosk) == ScreenFeed(CAMERA, until)
            for token, who in (("ann_back", ann), ("bea", bea), ("cam", cam)):   # background, never visible, not named
                assert await screens.feed_of(tokens[token], NOW, person_id=who) is None
    run(go())


def test_a_token_reads_back_only_for_its_own_owner_and_only_until_its_time_is_up(db_url: str) -> None:
    home = household(db_url)
    ann, bea = person(db_url, home, "Ann"), person(db_url, home, "Bea")
    token = str(uuid4())

    async def go() -> None:
        async with stores(db_url) as screens:
            await screens.opened(home, ann, token)
            await screens.person_visible(ann, token, True)
            until = NOW + timedelta(seconds=90)
            await screens.show_feed(home, CAMERA, until, (ann,), (), 60)
            assert await screens.feed_of(token, NOW, person_id=bea) is None
            assert await screens.feed_of(token, NOW) is None
            assert await screens.feed_of(token, until - timedelta(seconds=1), person_id=ann) is not None
            assert await screens.feed_of(token, until, person_id=ann) is None
    run(go())


def test_a_later_feed_replaces_an_earlier_and_dismissing_takes_it_off_one_screen_only(db_url: str) -> None:
    home = household(db_url)
    ann = person(db_url, home, "Ann")
    first, second = str(uuid4()), str(uuid4())

    async def go() -> None:
        async with stores(db_url) as screens:
            for token in (first, second):
                await screens.opened(home, ann, token)
                await screens.person_visible(ann, token, True)
            until = NOW + timedelta(seconds=90)
            await screens.show_feed(home, CAMERA, until, (ann,), (), 60)
            await screens.show_feed(home, "camera.zq_hall", until, (ann,), (), 60)
            assert (await screens.feed_of(first, NOW, person_id=ann)) == ScreenFeed("camera.zq_hall", until)
            await screens.dismiss_feed(first, person_id=ann)
            assert await screens.feed_of(first, NOW, person_id=ann) is None
            assert await screens.feed_of(second, NOW, person_id=ann) is not None
    run(go())


def test_clearing_takes_it_off_every_screen_of_the_household_and_no_other(db_url: str) -> None:
    home, other = household(db_url), household(db_url)
    ann, zed = person(db_url, home, "Ann"), person(db_url, other, "Zed")
    mine, theirs = str(uuid4()), str(uuid4())

    async def go() -> None:
        async with stores(db_url) as screens:
            await screens.opened(home, ann, mine)
            await screens.opened(other, zed, theirs)
            await screens.person_visible(ann, mine, True)
            await screens.person_visible(zed, theirs, True)
            until = NOW + timedelta(seconds=90)
            await screens.show_feed(home, CAMERA, until, (ann, zed), (), 60)   # zed is another household's: not shown
            assert await screens.feed_of(theirs, NOW, person_id=zed) is None
            await screens.show_feed(other, CAMERA, until, (zed,), (), 60)
            assert await screens.clear_feed(home) == 1
            assert await screens.clear_feed(home) == 0
            assert await screens.feed_of(mine, NOW, person_id=ann) is None
            assert await screens.feed_of(theirs, NOW, person_id=zed) is not None
    run(go())


def test_the_feed_goes_with_the_screen_when_it_closes(db_url: str) -> None:
    home = household(db_url)
    ann = person(db_url, home, "Ann")
    token = str(uuid4())

    async def go() -> None:
        async with stores(db_url) as screens:
            screen = await screens.opened(home, ann, token)
            await screens.person_visible(ann, token, True)
            await screens.show_feed(home, CAMERA, NOW + timedelta(seconds=90), (ann,), (), 60)
            await screens.closed(screen)
            assert await screens.feed_of(token, NOW, person_id=ann) is None
            assert scalar(db_url, "SELECT count(*) FROM live_screens WHERE feed_camera IS NOT NULL") == 0
    run(go())
