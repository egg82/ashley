"""A screen bench is nobody's bench: no person-scoped read of the Workshop returns it, counts it or reacts to it, and the
ownerless queries (`of_kind`, `unseen`, the files sweep, the carried-turn titles) leave it out."""

from ashley.workshop.commands import Move
from ashley.workshop.model import HER, By, Owner, Place
from ashley.workshop.workshop import BenchNotFound
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from screen_bench_support import count, device, household, person, shop


def test_no_person_read_returns_or_counts_a_screen_bench(db_url: str) -> None:
    home = household(db_url)
    me = Owner(home, person(db_url, home))
    tablet = device(db_url, home)

    async def scenario() -> None:
        async with shop(db_url) as (workshop, _):
            await workshop.apply_screen(home, tablet, Move(HER, 4, Place(0, "large")))
            await workshop.apply_screen(home, tablet, Move(By(me.person_id), 1, Place(2, "small")))
            bench_id = count(db_url, "SELECT id FROM benches WHERE device_id = %s", tablet)
            assert await workshop.open_benches(me) == [] and await workshop.closed_benches(me) == []
            for call in (workshop.read(me, bench_id), workshop.log(me, bench_id), workshop.close(me, bench_id),
                         workshop.reopen(me, bench_id)):
                try:
                    await call
                except BenchNotFound:
                    continue
                raise AssertionError("a screen bench was reachable as a person's")
            for kind in ("clock", "home", "controls", "conversation"):
                assert await workshop.of_kind(home, kind) == ()
            assert await workshop.unseen(0, 10, 5) == ()

    run(scenario())
