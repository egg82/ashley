"""What the reaction logs and stores: the done log's fields, and that no piece word reaches a turn, a handed message or a log."""

import re
from dataclasses import replace

import pytest
from ashley.channels.wake import bench_reacts
from ashley.channels.wake.bench_react_config import CONFIG
from ashley.channels.wake.bench_reacts import BenchReacts
from bench_reacts_blind_support import OLD, QUIETLY, SAYS, SENTINEL, last_message, logged, react, start_logs, world
from contract.conversations_support import run


def test_no_piece_word_reaches_a_turn_or_the_prompt_message_or_any_log(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start_logs()
            bench = await w.bench(title=SENTINEL)
            piece = await w.person_adds(bench, title=f"{SENTINEL}-title")
            await w.person_edits(bench, piece, 1)
            w.quiet(OLD)
            w.model.script = [SAYS]
            reacts = BenchReacts()
            await reacts.sweep()
            await w.person_edits(bench, piece, 2)
            w.quiet(OLD)
            w.model.script = [QUIETLY]
            await reacts.sweep()
            assert len(w.model.prompts) == 2
            assert SENTINEL not in w.everything_stored()
            assert all(SENTINEL not in last_message(p) for p in w.model.prompts)
            _, text = logged(capsys, "bench_reacts.done")
            assert "bench_reacts.done" in text and SENTINEL not in text
    run(go())


def test_the_done_log_has_the_bench_the_commands_the_outcome_and_a_duration(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start_logs()
            bench = await w.bench()
            piece = await w.person_adds(bench)
            await w.person_edits(bench, piece, 1)
            reacts = BenchReacts()
            w.quiet(OLD)
            w.model.script = [SAYS]
            await reacts.sweep()
            await react(w, reacts, bench, piece, 2, QUIETLY)
            done, _ = logged(capsys, "bench_reacts.done")
            assert [(d["bench"], d["commands"], d["outcome"]) for d in done] == [
                (str(bench), "2", "reply"), (str(bench), "1", "none")]
            assert all(d["duration_ms"].isdigit() for d in done)
    run(go())


def test_a_sweep_with_nothing_to_do_logs_no_reaction(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start_logs()
            bench = await w.bench()
            await w.person_adds(bench)
            assert await BenchReacts().sweep() == 0
            for event in ("bench_reacts.done", "bench_reacts.capped"):
                assert logged(capsys, event)[0] == []
            assert w.turns() == []
    run(go())


def test_the_log_counts_every_command_handed_though_the_turn_names_only_the_latest(
        db_url: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start_logs()
            monkeypatch.setattr(bench_reacts, "CONFIG", replace(CONFIG, listed=2))
            bench = await w.bench()
            piece = await w.person_adds(bench)
            seqs = [piece] + [await w.person_edits(bench, piece, v) for v in range(1, 5)]
            w.quiet(OLD)
            w.model.script = [SAYS]
            assert await BenchReacts().sweep() == 1
            [done], _ = logged(capsys, "bench_reacts.done")
            assert done["commands"] == "5"
            said = last_message(w.model.prompts[0])
            assert re.search(rf"#{seqs[-1]}\b", said) and not re.search(rf"#{seqs[0]}\b", said)
    run(go())
