"""Which screens are open and in the foreground, from any pod: a page's report is listed beside its screen, a screen
nobody has refreshed within the lease is not listed, another pod's view reads the same rows, and the rows dead pods left
behind go at the next opening in the household while current ones stay. Time moves in the database, never by waiting."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from ashley.db.pool import PoolDatabase
from ashley.live.postgres_screens import LEFT_BEHIND_S, PostgresScreens
from ashley.live.screens import OpenScreen, Screens
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar
from screen_bench_support import device

LEASE_S = 60.0


@asynccontextmanager
async def pod(url: str) -> AsyncGenerator[Screens]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresScreens(db)
    finally:
        await db.close()


def age(url: str, screen_id: int, seconds: float) -> None:
    scalar(url, "WITH u AS (UPDATE live_screens SET seen_at = now() - make_interval(secs => %s) WHERE id = %s "
                "RETURNING 1) SELECT count(*) FROM u", (seconds, screen_id))


def test_a_screen_is_listed_with_what_its_page_reported(db_url: str) -> None:
    home = household(db_url)
    alana, sam = person(db_url, home, "Alana"), person(db_url, home, "Sam")
    hall = device(db_url, home, "hall")
    tokens = [str(uuid4()) for _ in range(3)]

    async def go() -> None:
        async with pod(db_url) as screens:
            await screens.opened(home, alana, tokens[0])
            await screens.opened(home, sam, tokens[1])
            await screens.device_opened(home, hall, tokens[2])
            assert await screens.open_screens(home, LEASE_S) == (
                OpenScreen(alana, None, None), OpenScreen(sam, None, None), OpenScreen(None, hall, None))
            await screens.person_visible(alana, tokens[0], True)
            await screens.person_visible(sam, tokens[1], False)
            await screens.device_visible(hall, tokens[2], True)
            listed = await screens.open_screens(home, LEASE_S)
            assert listed == (OpenScreen(alana, None, True), OpenScreen(sam, None, False), OpenScreen(None, hall, True))
            assert [s.kind for s in listed] == ["web", "web", "kiosk"]
            await screens.person_visible(alana, tokens[0], False)
            assert (await screens.open_screens(home, LEASE_S))[0].visible is False
    run(go())


def test_a_screen_past_its_lease_is_not_listed_and_a_refresh_brings_it_back(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def go() -> None:
        async with pod(db_url) as screens:
            kept, quiet = await screens.opened(home, alana, str(uuid4())), await screens.opened(home, alana, str(uuid4()))
            age(db_url, quiet, LEASE_S + 5)
            assert len(await screens.open_screens(home, LEASE_S)) == 1
            await screens.beat(quiet)
            assert len(await screens.open_screens(home, LEASE_S)) == 2
            await screens.closed(kept)
            assert len(await screens.open_screens(home, LEASE_S)) == 1
    run(go())


def test_another_pods_view_reads_what_this_pod_recorded(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)
    token = str(uuid4())

    async def go() -> None:
        async with pod(db_url) as here, pod(db_url) as elsewhere:
            await here.opened(home, alana, token)
            await here.person_visible(alana, token, True)
            assert await elsewhere.open_screens(home, LEASE_S) == (OpenScreen(alana, None, True),)
            await elsewhere.person_visible(alana, token, False)
            assert await here.open_screens(home, LEASE_S) == (OpenScreen(alana, None, False),)
    run(go())


def test_a_report_changes_only_the_reporters_own_screen_and_the_listing_only_its_household(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    alana, sam, stranger = person(db_url, home, "Alana"), person(db_url, home, "Sam"), person(db_url, other, "Ines")
    hall = device(db_url, home)
    token = str(uuid4())

    async def go() -> None:
        async with pod(db_url) as screens:
            await screens.opened(home, alana, token)
            await screens.opened(home, sam, token)   # the same token a page of someone else happened to make
            await screens.device_opened(home, hall, token)
            await screens.opened(other, stranger, str(uuid4()))
            await screens.person_visible(sam, token, True)
            assert await screens.open_screens(home, LEASE_S) == (
                OpenScreen(alana, None, None), OpenScreen(sam, None, True), OpenScreen(None, hall, None))
            await screens.person_visible(stranger, token, True)   # not their token: nothing to change
            await screens.person_visible(alana, str(uuid4()), True)
            assert await screens.open_screens(other, LEASE_S) == (OpenScreen(stranger, None, None),)
            assert (await screens.open_screens(home, LEASE_S))[0].visible is None
    run(go())


def test_rows_left_by_dead_pods_go_at_the_next_opening_in_the_household_and_current_ones_stay(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    alana, sam, stranger = person(db_url, home, "Alana"), person(db_url, home, "Sam"), person(db_url, other, "Ines")
    hall = device(db_url, home)

    async def go() -> None:
        async with pod(db_url) as screens:
            dead_person = await screens.opened(home, alana, str(uuid4()))
            dead_device = await screens.device_opened(home, hall, str(uuid4()))
            just_in = await screens.opened(home, alana, str(uuid4()))
            elsewhere = await screens.opened(other, stranger, str(uuid4()))
            age(db_url, dead_person, LEFT_BEHIND_S + 60)
            age(db_url, dead_device, LEFT_BEHIND_S + 60)
            age(db_url, just_in, LEFT_BEHIND_S - 60)
            age(db_url, elsewhere, LEFT_BEHIND_S + 60)
            opened = await screens.opened(home, sam, str(uuid4()))   # a different person's opening prunes the household
            ids = scalar(db_url, "SELECT coalesce(json_agg(id ORDER BY id), '[]') FROM live_screens")
            assert ids == sorted([just_in, elsewhere, opened])
    run(go())
