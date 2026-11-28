"""`Recorded`, the bench-act eval's fake tools: what it counts as a change, and how it answers a piece she adds."""

import asyncio
import json

from ashley.evals import bench_act
from ashley.evals.bench_act_fakes import Recorded
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import bench_capture
from ashley.tools.tools import Catalogue, Tools


class _Nothing(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        raise AssertionError(f"{call.name} should have been answered by the fake")


def recorded() -> Recorded:
    return Recorded(_Nothing(), bench_capture.load(bench_act.CAPTURE))


def ask(source: Recorded, name: str, **arguments: object) -> dict[str, object]:
    got = asyncio.run(source.call(ToolCall(f"c{len(source.calls)}", name, dict(arguments))))
    body: dict[str, object] = json.loads(got.content)
    return body


def test_a_last_run_read_is_not_a_change() -> None:
    source = recorded()
    ask(source, "bench_run", piece_id=6, base_version=4, language="build123d")
    again = ask(source, "bench_last_run", piece_id=6)
    assert again["outcome"] == "ran"
    assert [c.name for c in source.changes] == ["bench_run"]


def test_a_last_run_of_a_piece_not_run_says_no_run() -> None:
    source = recorded()
    assert ask(source, "bench_last_run", piece_id=6) == {"piece_id": 6, "run": None}
    assert source.changes == []
