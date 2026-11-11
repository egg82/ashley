"""Support for the blind finish suite (`decisions.md`, "A Claude Code job is finished when `out/RESULT.md` exists"): one
Claude Code job on the bench-jobs blind suite's world, stepped through `bench_session.step` at times the test chooses, so
the idle clock is driven by the `now` the tick is given and never by sleeping. Every tick re-reads the job from the
store, as another pod would."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from bjb_support import MARK_BRIEF, World, bench_session, cfg, state_of
from ashley.errands.bench_job_model import Outcome
from ashley.errands.jobs_config import JobsConfig
from ashley.herdr.model import Status

NUDGE = bench_session.NUDGE
NO_RESULT = bench_session.NO_RESULT


def config(**changes: Any) -> JobsConfig:
    return replace(cfg(), **changes)


@dataclass
class Run:
    w: World
    job_id: int
    sid: str
    t0: datetime

    async def tick(self, at: float = 0.0, with_config: JobsConfig | None = None) -> Outcome | None:
        """One step, `at` seconds after the first one."""
        job = await self.w.jobs.get(self.w.owner.household_id, self.w.owner.person_id, self.job_id)
        assert job is not None
        return await bench_session.step(job, now=self.t0 + timedelta(seconds=at), config=with_config or cfg())

    def settle(self, status: Status) -> None:
        self.w.bridge.settle(self.sid, status)

    def write(self, files: dict[str, bytes]) -> None:
        self.w.bridge.out[self.sid].update(files)

    @property
    def state(self) -> str:
        return state_of(self.w.url, self.job_id)

    @property
    def prompts(self) -> list[str]:
        return self.w.bridge.prompts[self.sid]

    @property
    def nudges(self) -> list[str]:
        """Every prompt after the brief's own."""
        return self.prompts[1:]


async def begun(w: World) -> Run:
    """A Claude Code job whose first step started the session and prompted it: the session is `working`."""
    await w.started("claude_code", pieces=[], brief=MARK_BRIEF)
    job = await w.claimed("claude_code")
    t0 = datetime.now(UTC)
    assert await bench_session.step(job, now=t0, config=cfg()) is None
    (sid,) = w.bridge.sessions_
    assert len(w.bridge.prompts[sid]) == 1
    return Run(w, job.id, sid, t0)
