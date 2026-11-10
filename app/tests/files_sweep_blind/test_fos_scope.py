"""The sweep is scoped to the files' intake prefix: nothing outside it is listed for judging or deleted."""

from ashley.files.intake import PREFIX
from ashley.looks.keys import PREFIX as LOOK_PREFIX
from files_sweep_blind_support import OLD, key, go, rig


def test_a_look_key_and_anything_else_outside_the_prefix_is_never_deleted(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            outside = [f"{LOOK_PREFIX}1/{'a' * 64}", "other/1/x", "bench", "benchmark/1/x", "Bench/1/x", "x/bench/1/y", ""]
            for s in r.sites:
                for k in outside:
                    s.keep(k, age=OLD * 50)
                s.keep(key(1), age=OLD)
            await r.passes(4)
            assert all(all(r.holders(k)) for k in outside)
            assert r.holders(key(1)) == [False, False]

    go(scenario())


def test_only_the_prefix_is_listed_and_only_prefixed_keys_are_deleted(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
                s.keep(f"{LOOK_PREFIX}9/{'b' * 64}", age=OLD)
            await r.passes(3)
            for s in r.sites:
                assert s.of("listing") and all(p == PREFIX for p in s.of("listing"))
                assert s.of("delete") == [key(1)]
                assert not s.of("put")

    go(scenario())


def test_a_look_picture_is_not_a_candidate(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            look = f"{LOOK_PREFIX}1/{'c' * 64}"
            r.sites[0].keep(look, age=OLD)
            r.sites[0].keep(key(1), age=OLD)
            await r.pass_()
            assert await r.candidates.load() == frozenset({key(1)})

    go(scenario())
