"""A bench turn makes at most `max_runs_per_turn` runs of its own: the next is refused `hand_off`, counted from the runs
recorded against the turn so a resume counts the same; a turn that cannot hand off, and a worker's runs, are not capped."""

from ashley.errands.jobs_config import CONFIG
from ashley.inference.model import ToolCall
from ashley.tools.bench_run import BenchRunTools
from bench_jobs_support import Jobs, db_url as db_url, jobs_world, migrated_template as migrated_template
from contract.conversations_support import run


async def run_once(tools: BenchRunTools, piece: int, n: int) -> str:
    got = await tools.call(ToolCall(f"r{n}", "bench_run", {"piece_id": piece, "base_version": 1, "language": "python"}))
    return got.content.split(":")[0] if got.is_error else "ok"


def turn_tools(w: Jobs, hand_off: bool = True) -> BenchRunTools:
    return BenchRunTools(w.s.household, w.s.person, w.s.bench, w.s.conversation, w.s.turn, hand_off=hand_off)


def test_the_run_after_the_cap_is_refused_hand_off_also_after_a_resume(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            piece = await w.piece("code", "c", "print(1)")
            got = [await run_once(turn_tools(w), piece, n) for n in range(CONFIG.max_runs_per_turn)]
            assert got == ["ok"] * CONFIG.max_runs_per_turn
            assert await run_once(turn_tools(w), piece, 9) == "hand_off"
            assert len(w.run.box.jobs) == CONFIG.max_runs_per_turn
    run(go())


def test_a_turn_that_cannot_hand_off_and_a_worker_are_not_capped(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            piece = await w.piece("code", "c", "print(1)")
            n = CONFIG.max_runs_per_turn + 2
            assert [await run_once(turn_tools(w, hand_off=False), piece, i) for i in range(n)] == ["ok"] * n
            worker = BenchRunTools(w.s.household, w.s.person, w.s.bench, hand_off=False)
            assert [await run_once(worker, piece, i) for i in range(n)] == ["ok"] * n
    run(go())
