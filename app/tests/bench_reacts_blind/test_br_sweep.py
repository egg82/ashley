"""`BenchReacts.sweep` over a real database with a scripted model: who triggers a turn and when, that nothing is handed
twice, the rate cap and its recovery, two sweepers storing one turn, the household boundary, and what the turn and the
logs may carry."""

import asyncio
import re

import pytest
from ashley import services
from ashley.channels import unprompted
from ashley.channels.wake import runner
from ashley.channels.wake.bench_react_config import CONFIG
from ashley.channels.wake.bench_reacts import BenchReacts
from ashley.conversations.conversations import Conversations
from ashley.senses.wakes import Due, NullWakes, Wakes
from bench_reacts_blind_support import (OLD, PAUSE, QUIETLY, SAYS, SENTINEL, last_message, react,
                                         world)
from contract.conversations_support import run, scalar


def test_nothing_happens_within_the_pause_and_one_turn_after_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.model.script = [SAYS]
            reacts = BenchReacts()
            assert await reacts.sweep() == 0
            w.quiet(PAUSE - 5)
            assert await reacts.sweep() == 0
            assert w.turns() == [] and w.model.prompts == [] and w.mark(bench) == 0
            w.quiet(PAUSE + 1)
            assert await reacts.sweep() == 1
            assert len(w.model.prompts) == 1 and w.mark(bench) == 1
            [(author, _, source), (hers, _, none)] = w.turns()
            assert (author, source, hers, none) == ("household", f"bench_react:{bench}:1", "ashley", None)
    run(go())


def test_a_sweep_with_no_benches_returns_zero(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await BenchReacts().sweep() == 0 and w.turns() == []
    run(go())


def test_the_turn_is_handed_the_commands_by_number_type_and_kind(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench, kind="document")
            edit = await w.person_edits(bench, piece, 1)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await BenchReacts().sweep() == 1
            said = last_message(w.model.prompts[0])
            assert f"#{piece} add document" in said and f"#{edit} edit document" in said
            assert SENTINEL not in said
    run(go())


def test_the_same_changes_are_never_handed_twice(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet(OLD)
            w.model.script = [SAYS, SAYS, SAYS]
            reacts = BenchReacts()
            assert await reacts.sweep() == 1
            for _ in range(3):
                assert await reacts.sweep() == 0
            assert await BenchReacts().sweep() == 0
            assert len(w.model.prompts) == 1 and len(w.turns()) == 2
            edit = await w.person_edits(bench, piece, 1)
            w.quiet(OLD)
            assert await reacts.sweep() == 1
            second = last_message(w.model.prompts[1])
            assert f"#{edit} edit" in second and not re.search(rf"#{piece}\b", second)
            assert w.mark(bench) == edit
    run(go())


def test_a_new_edit_during_the_pause_postpones_the_reaction_and_it_covers_both(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet(OLD)
            edit = await w.person_edits(bench, piece, 1)
            w.model.script = [SAYS]
            reacts = BenchReacts()
            assert await reacts.sweep() == 0
            w.quiet(OLD)
            assert await reacts.sweep() == 1
            said = last_message(w.model.prompts[0])
            assert re.search(rf"#{piece}\b", said) and re.search(rf"#{edit}\b", said)
    run(go())


def test_her_commands_never_start_a_reaction(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.she_adds(bench)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await BenchReacts().sweep() == 0
            assert w.model.prompts == [] and w.turns() == []
    run(go())


def test_her_command_after_a_reaction_does_not_start_another(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            reacts = BenchReacts()
            await react(w, reacts, bench, piece, 1)
            await w.she_adds(bench)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 0 and len(w.model.prompts) == 1
    run(go())


def test_a_closed_bench_is_not_reacted_to(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            await w.workshop.close(w.home.owner, bench)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await BenchReacts().sweep() == 0
            assert w.model.prompts == [] and w.turns() == [] and w.mark(bench) == 0
    run(go())


def test_the_batch_bounds_one_sweep_and_the_next_takes_the_rest(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            benches = [await w.bench(title=f"b{n}") for n in range(CONFIG.batch + 1)]
            for b in benches:
                await w.person_adds(b)
            w.quiet(OLD)
            w.model.script = [SAYS] * len(benches)
            reacts = BenchReacts()
            assert await reacts.sweep() == CONFIG.batch
            assert sorted(w.mark(b) > 0 for b in benches) == [False] + [True] * CONFIG.batch
            assert await reacts.sweep() == 1
            assert all(w.mark(b) == 1 for b in benches) and await reacts.sweep() == 0
    run(go())


def test_a_bench_is_reacted_to_in_its_own_thread_and_never_another_households(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, households=2) as w:
            a, b = w.homes
            ba = await w.bench(a)
            await w.person_adds(ba, home=a)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await BenchReacts().sweep() == 1
            conversations = services.get(Conversations)
            mine = await conversations.on_thread(a.id, f"bench:{ba}")
            assert mine is not None and [t.author for t in mine.turns] == ["household", "ashley"]
            assert await conversations.on_thread(b.id, f"bench:{ba}") is None
    run(go())


def test_two_households_react_each_for_its_own_bench(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, households=2) as w:
            a, b = w.homes
            ba, bb = await w.bench(a), await w.bench(b)
            await w.person_adds(ba, home=a)
            await w.person_adds(bb, home=b)
            w.quiet(OLD)
            w.model.script = [SAYS, SAYS]
            assert await BenchReacts().sweep() == 2
            conversations = services.get(Conversations)
            for home, bench in ((a, ba), (b, bb)):
                got = await conversations.on_thread(home.id, f"bench:{bench}")
                assert got is not None and len(got.turns) == 2
    run(go())


def test_reply_none_posts_nothing_to_the_talk_and_still_marks_the_changes_seen(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet(OLD)
            w.model.script = [QUIETLY]
            reacts = BenchReacts()
            assert await reacts.sweep() == 1
            got = await services.get(Conversations).on_thread(w.home.id, f"bench:{bench}")
            assert got is not None and unprompted.shown(got.turns) == []
            assert w.mark(bench) == 1
            assert await reacts.sweep() == 0
    run(go())


def test_a_reply_is_an_ordinary_turn_in_the_talk(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet(OLD)
            w.model.script = [SAYS]
            await BenchReacts().sweep()
            got = await services.get(Conversations).on_thread(w.home.id, f"bench:{bench}")
            assert got is not None
            shown = unprompted.shown(got.turns)
            assert [t.text for t in shown if t.author == "ashley"] == [SAYS.text]
    run(go())


def test_two_sweepers_over_the_same_changes_store_one_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet(OLD)
            w.model.script = [SAYS, SAYS]
            await asyncio.gather(BenchReacts().sweep(), BenchReacts().sweep())
            source = f"bench_react:{bench}:1"
            assert [s for _, _, s in w.turns()].count(source) == 1
            assert [a for a, _, _ in w.turns()].count("ashley") <= 1
    run(go())


def test_changes_handed_in_again_after_a_lost_mark_are_the_same_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet(OLD)
            w.model.script = [SAYS, SAYS]
            assert await BenchReacts().sweep() == 1
            scalar(db_url, "WITH d AS (DELETE FROM bench_reactions RETURNING 1) SELECT count(*) FROM d")
            await BenchReacts().sweep()
            source = f"bench_react:{bench}:1"
            assert [s for _, _, s in w.turns()].count(source) == 1
            assert [a for a, _, _ in w.turns()].count("ashley") == 1
    run(go())


def test_the_wakes_loop_runs_the_bench_reaction_every_round(db_url: str) -> None:
    class Stop(Exception):
        pass

    class Idle(NullWakes):
        async def due(self, limit: int) -> tuple[Due, ...]:
            return ()

        async def prune(self, older_than_s: float) -> int:
            return 0

    async def go() -> None:
        async with world(db_url) as w:
            services.register(Wakes, Idle())
            try:
                bench = await w.bench()
                await w.person_adds(bench)
                w.quiet(OLD)
                w.model.script = [SAYS]
                rounds = 0

                async def sleep(_: float) -> None:
                    nonlocal rounds
                    rounds += 1
                    if rounds == 2:
                        raise Stop

                with pytest.raises(Stop):
                    await runner.run(sleep)
                assert w.mark(bench) == 1 and len(w.model.prompts) == 1
            finally:
                services.unregister(Wakes)
    run(go())
