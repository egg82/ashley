"""What a bench job's agent may do with a bench (`ashley.errands.bench_jobs`): a Proxy over the bench tools that offers
only `bench_read_piece`, `bench_add`, `bench_add_file`, `bench_edit` and `bench_run`, and holds each to the pieces
the job was given or made. It reads the pieces it was named and the ones it made; it edits and runs only the ones it
made, so jobs running side by side never change the same piece, and it has no read of the whole bench, no remove,
move, archive or propose, and no house, mail or Claude Code tools. A piece it adds is recorded on the job as it is made,
so a retaken attempt knows it."""

import json
import logging
import time
from dataclasses import replace

from .. import logs, services
from ..errands.bench_jobs import BenchJobs, Job, JobsUnavailable
from ..inference.model import Tier, ToolCall, ToolResult
from . import bench_results
from .action_judge import Vetting
from .tools import Catalogue, Tools
from collections.abc import Sequence

log = logging.getLogger("ashley.tools")
READ, ADD, ADD_FILE, EDIT, RUN = "bench_read_piece", "bench_add", "bench_add_file", "bench_edit", "bench_run"
OFFERED = (READ, ADD, ADD_FILE, EDIT, RUN)
_ADDS = (ADD, ADD_FILE)
_OWN = (EDIT, RUN)


class JobScope(Tools):
    def __init__(self, inner: Tools, job: Job) -> None:
        self._inner = inner
        self._job = job
        self._named = frozenset(n.piece_id for n in job.pieces)
        self._made = set(job.made)

    async def catalogue(self) -> Catalogue:
        """The inner catalogue with only the offered tools. Raises ToolsUnavailable as the inner does."""
        got = await self._inner.catalogue()
        return replace(got, specs=tuple(s for s in got.specs if s.name in OFFERED))

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        if call.name not in OFFERED:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        wanted = call.arguments.get("piece_id")
        piece = wanted if type(wanted) is int else None
        if call.name == READ and piece not in self._named | self._made:
            return bench_results.failed(call, started, "no_such_piece", "that piece is not one you were given or made",
                                        job=self._job.id)
        if call.name in _OWN and piece not in self._made:
            return bench_results.failed(call, started, "not_yours", "you change and run only the pieces you made",
                                        job=self._job.id)
        got = await self._inner.call(call)
        if call.name in _ADDS and not got.is_error:
            await self._record(got)
        return got

    async def _record(self, result: ToolResult) -> None:
        try:
            made = json.loads(result.content).get("piece_id")
        except (ValueError, AttributeError):
            return
        if type(made) is not int:
            return
        self._made.add(made)
        try:
            await services.get(BenchJobs).made(self._job.id, self._job.attempts, made)
        except JobsUnavailable:
            logs.warning(log, "bench_jobs.made_unrecorded", job=self._job.id)

    async def tier(self, call: ToolCall) -> Tier | None:
        return await self._inner.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self._inner.vetted(call, words)

    async def shown(self, call: ToolCall) -> str | None:
        return await self._inner.shown(call)
