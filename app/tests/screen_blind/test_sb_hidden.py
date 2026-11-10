"""Contract 15 at the service: no person-scoped read of the Workshop or of a bench's talk returns, lists or counts a
screen bench, though a person (and her) has made accepted commands on it; a control bench of the same household shows
in every one of them, so each assertion could fail."""

import pytest
from ashley.conversations.model import Hearer, NewTurn
from ashley.workshop.commands import Add, Remove
from ashley.workshop.model import By, Text
from ashley.workshop.workshop import BenchNotFound
from contract.conversations_support import run, scalar, service
from sb_support import Env, benches_of, env, mv

SCREEN_KINDS = ("clock", "home", "conversation", "controls")
MARK = "zqSCREEN-TITLE"


async def both(e: Env) -> tuple[int, int]:
    """A bench of Alana's with a note, and the tablet's screen bench after commands by Alana, Sam and her: their ids."""
    w = e.world
    bench = (await e.workshop.open(w.alana, "Plan")).id
    await e.workshop.apply(w.alana, bench, Add(By(w.alana.person_id), "note", Text("n", "b"), "small"))
    await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, 1, 3))
    await e.workshop.apply_screen(w.home, w.tablet, mv(w.sam, 2, 0))
    await e.workshop.apply_screen(w.home, w.tablet, mv(None, 3, 1))
    [screen] = benches_of(w.url, w.tablet)
    return bench, screen


def test_k15_open_and_closed_benches_list_only_the_persons_own(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            bench, screen = await both(e)
            assert [b.id for b in await e.workshop.open_benches(w.alana)] == [bench]
            assert await e.workshop.open_benches(w.sam) == [] and await e.workshop.open_benches(w.zed) == []
            for owner in (w.alana, w.sam, w.zed):
                assert await e.workshop.closed_benches(owner) == []
            await e.workshop.close(w.alana, bench)
            assert [b.id for b in await e.workshop.closed_benches(w.alana)] == [bench]
            assert screen not in [b.id for o in (w.alana, w.sam) for b in await e.workshop.open_benches(o)]

    run(scenario())


def test_k15_a_screen_bench_is_not_found_by_read_log_close_reopen_set_work_or_apply(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            _, screen = await both(e)
            for owner in (w.alana, w.sam, w.zed):
                for call in (lambda o=owner: e.workshop.read(o, screen), lambda o=owner: e.workshop.log(o, screen),
                             lambda o=owner: e.workshop.close(o, screen), lambda o=owner: e.workshop.reopen(o, screen),
                             lambda o=owner: e.workshop.set_work(o, screen, "x"),
                             lambda o=owner: e.workshop.apply(o, screen, Remove(By(o.person_id), 1)),
                             lambda o=owner: e.workshop.apply(o, screen, Add(By(o.person_id), "note", Text("n", ""), "small"))):
                    with pytest.raises(BenchNotFound):
                        await call()
            assert scalar(db_url, "SELECT closed_at FROM benches WHERE id = %s", (screen,)) is None

    run(scenario())


@pytest.mark.parametrize("kind", SCREEN_KINDS)
def test_k15_of_kind_never_returns_a_screens_piece(db_url: str, kind: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            bench, _ = await both(e)
            assert await e.workshop.of_kind(w.home, kind) == ()
            assert [p.bench_id for p in await e.workshop.of_kind(w.home, "note")] == [bench]

    run(scenario())


def test_k15_unseen_never_lists_a_screen_bench_whoever_changed_it(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, screen = await both(e)
            found = await e.workshop.unseen(0.0, 50, 10)
            assert [u.bench_id for u in found] == [bench]
            assert screen not in [u.bench_id for u in found]

    run(scenario())


def test_k15_a_bench_talk_on_a_screen_benchs_thread_names_no_bench_title(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            bench, screen = await both(e)
            scalar(db_url, "UPDATE benches SET title = %s WHERE id = %s RETURNING id", (MARK, screen))
            async with service(db_url) as conv:
                said: dict[str, int] = {}
                for name, thread in (("plan", f"bench:{bench}"), ("screen", f"bench:{screen}")):
                    talk = await conv.for_thread(w.home, thread, "brainstorm", [w.alana.person_id])
                    turn = await conv.add_turn(talk.id, NewTurn("person", f"words {name}", w.alana.person_id, "shared"))
                    said[name] = turn.id
                now = await conv.start(w.home, "chat", [w.alana.person_id])
                last = await conv.add_turn(now.id, NewTurn("person", "and now", w.alana.person_id, "shared"))
                got = await conv.carried(Hearer(w.home, w.alana.person_id, owner_only=False), now.id, last.id, "and now", 10, 0)
                assert {t.text for t in got.recent} >= {"words plan", "words screen"}
                assert got.places[said["plan"]].bench_title == "Plan"
                assert got.places[said["screen"]].bench_title is None
                assert MARK not in repr(got.places)

    run(scenario())


def test_k15_the_screen_benchs_pieces_and_commands_stay_out_of_other_households_reads(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            await both(e)
            other = (await e.workshop.open(w.zed, "Zed's")).id
            assert [b.id for b in await e.workshop.open_benches(w.zed)] == [other]
            assert await e.workshop.of_kind(w.next_door, "controls") == ()

    run(scenario())
