"""The reaction's rate cap over a real database: at most `max_reactions` per bench in `window_s`, its log once per wait,
and the recovery when a record leaves the window."""

import re

import pytest
from ashley.channels.wake.bench_react_config import CONFIG
from ashley.channels.wake.bench_reacts import BenchReacts
from bench_reacts_blind_support import OLD, SAYS, last_message, logged, react, start_logs, world
from contract.conversations_support import run


def test_the_cap_holds_a_fourth_reaction_in_the_window_and_logs_it_once_per_wait(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start_logs()
            bench = await w.bench()
            piece = await w.person_adds(bench)
            reacts = BenchReacts()
            seqs = [piece]
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 1
            for v in range(1, CONFIG.max_reactions):
                seqs.append(await react(w, reacts, bench, piece, v))
            assert len(w.model.prompts) == CONFIG.max_reactions
            held = await w.person_edits(bench, piece, CONFIG.max_reactions)
            w.quiet(OLD)
            w.model.script = [SAYS]
            for _ in range(3):
                assert await reacts.sweep() == 0
            assert len(w.model.prompts) == CONFIG.max_reactions and w.mark(bench) == seqs[-1]
            capped, _ = logged(capsys, "bench_reacts.capped")
            assert [c["bench"] for c in capped] == [str(bench)]
            assert held > seqs[-1]
    run(go())


def test_a_capped_bench_is_reacted_to_once_a_record_leaves_the_window_with_only_what_it_missed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            reacts = BenchReacts()
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 1
            seqs = [piece] + [await react(w, reacts, bench, piece, v) for v in range(1, CONFIG.max_reactions)]
            held = await w.person_edits(bench, piece, CONFIG.max_reactions)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 0
            w.age_reaction(bench, seqs[0], CONFIG.window_s - 30)
            assert await reacts.sweep() == 0
            w.age_reaction(bench, seqs[0], CONFIG.window_s + 30)
            assert await reacts.sweep() == 1
            said = last_message(w.model.prompts[-1])
            assert re.search(rf"#{held}\b", said) and not re.search(rf"#{seqs[-1]}\b", said)
            assert w.mark(bench) == held
    run(go())


def test_the_cap_is_per_bench(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            one, two = await w.bench(title="one"), await w.bench(title="two")
            p1 = await w.person_adds(one)
            reacts = BenchReacts()
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 1
            for v in range(1, CONFIG.max_reactions):
                await react(w, reacts, one, p1, v)
            await w.person_edits(one, p1, CONFIG.max_reactions)
            await w.person_adds(two)
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 1
            assert w.mark(two) == 1
    run(go())


def test_a_bench_that_waits_again_after_recovering_is_logged_again(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start_logs()
            bench = await w.bench()
            piece = await w.person_adds(bench)
            reacts = BenchReacts()
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 1
            seqs = [piece] + [await react(w, reacts, bench, piece, v) for v in range(1, CONFIG.max_reactions)]
            await w.person_edits(bench, piece, CONFIG.max_reactions)
            w.quiet(OLD)
            assert await reacts.sweep() == 0
            for s in seqs:
                w.age_reaction(bench, s, CONFIG.window_s + 30)
            w.model.script = [SAYS]
            assert await reacts.sweep() == 1
            for v in range(CONFIG.max_reactions + 1, CONFIG.max_reactions * 2):
                await react(w, reacts, bench, piece, v)
            assert await reacts.sweep() == 0
            await w.person_edits(bench, piece, CONFIG.max_reactions * 2)
            w.quiet(OLD)
            assert await reacts.sweep() == 0
            assert len(logged(capsys, "bench_reacts.capped")[0]) == 2
    run(go())
