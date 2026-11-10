"""Her tool to answer a tidy finding (`ashley.tidy`): `bench_dismiss` marks a passage a cheap pass pointed at as fine as it
stands. The findings themselves come with `bench_read` (`to_check`); a finding she fixes with an ordinary edit clears
itself when its quote is gone from the piece."""

import time

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..tidy.tidy import Tidy, TidyUnavailable
from . import bench_results
from .bench_args import BadArguments, check_names, finding_id_of
from .tools import Catalogue, Tools

DISMISS = "bench_dismiss"
INSTRUCTIONS = (
    "bench_read may list `to_check`: passages in the bench's text pieces that a quick pass flagged as superseded, "
    "contradicting another passage, left-over debris or duplicated, each quoted exactly. It only points and can be wrong: "
    "check each against the pieces, fix the ones that are right with an ordinary edit (the flag clears once its quote is "
    "gone), and bench_dismiss the ones that are fine as they are.")
SPEC = ToolSpec(DISMISS, "Dismiss a `to_check` finding of bench_read: the flagged passage is fine as it stands and is not "
                "flagged again while it stays as it is.",
                {"type": "object", "properties": {"finding_id": {"type": "integer"}}, "required": ["finding_id"]}, outside=False, tier="runs")


class BenchTidyTools(Tools):
    def __init__(self, bench_id: int) -> None:
        self._bench = bench_id

    async def catalogue(self) -> Catalogue:
        return Catalogue((SPEC,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the record or the model did: each is an error result, logged `tools.call`."""
        started = time.monotonic()
        if call.name != DISMISS:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, SPEC)
            finding = finding_id_of(call.arguments)
            if not await services.get(Tidy).dismiss(self._bench, finding):
                return bench_results.failed(call, started, "no_such_finding", "no flagged passage with that id is on this "
                                            "bench: read it again", bench=self._bench, finding=finding)
            return bench_results.ok(call, started, {"dismissed": finding}, bench=self._bench, finding=finding)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except TidyUnavailable:
            return bench_results.failed(call, started, "unavailable", "the flags cannot be reached right now",
                                        bench=self._bench)
