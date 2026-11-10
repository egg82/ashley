"""The watch-tools eval against the live model: how she uses `watch`, `unwatch` and `watches`. Each case in
`watch_tools_cases.json` is a short talk on one thread through her real turn loop (`channels.respond`), `runs` times,
with a person who has one herdr bridge listing three Claude Code sessions (`watch_tools_fakes`). The last turn is
graded from the calls she made in it. A case expects `watch` (a call on the named session, with no `until` or with
`until` [[gone]] as the case says, and none on another), `unwatch` (a call on the named session, none on another) or
`nothing` (no `watch` or `unwatch` call at all). Measured, never gated.

Her watches are real rows of the scratch database the eval is pointed at, ended after each run. Logs `eval.watch_tools`
once per run of the eval: cases, runs, passes and duration_ms. Never a case's text, a reply or a call's arguments."""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import logs, services
from ..channels.model import Inbound
from ..channels.respond import respond
from ..connections.connections import Connections
from ..criteria.items import ItemPredicate
from ..herdr.bridge import Bridge
from ..inference.inference import Inference
from ..inference.model import ToolCall
from ..tools import watch_conditions
from ..tools.bench_args import BadArguments
from ..watches.config import CONFIG
from ..watches.watches import Watches
from .house import Seat, repeats
from .house_guard import RecordingInference, Step
from .watch_tools_fakes import EvalBridge, EvalConnections, id_of

log = logging.getLogger("ashley.evals")

CASES = Path(__file__).parent / "watch_tools_cases.json"
GONE = ((ItemPredicate("gone"),),)
WATCH_TOOLS = ("watch", "unwatch")


@dataclass(frozen=True)
class RunResult:
    case_id: str
    passed: bool
    seen: tuple[str, ...]
    tools: tuple[str, ...]
    repeats: int
    error: str | None


def load() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text())["cases"]


def until_of(call: ToolCall) -> str:
    """`none` for a watch with no `until`, `gone` for exactly [[gone]], else `other` (also one her tool refuses)."""
    try:
        parsed = watch_conditions.parse(call.arguments.get("until"), CONFIG.kinds["claude_session"].track)
    except BadArguments:
        return "other"
    return "none" if parsed is None else "gone" if parsed == GONE else "other"


def describe(call: ToolCall) -> str:
    """The call as one token for the report: its tool, the session it names by label and, for a watch, its `until`."""
    target = str(call.arguments.get("target"))
    named = next((s for s in ("ashley-wiring", "k8s-upgrade", "docs-pass") if id_of(s) == target), "?")
    return f"watch({named},{until_of(call)})" if call.name == "watch" else f"{call.name}({named})"


def passes(case: dict[str, Any], calls: list[ToolCall]) -> bool:
    acted = [c for c in calls if c.name in WATCH_TOOLS]
    if case["expect"] == "nothing":
        return not acted
    wanted = id_of(case["session"])
    same = [c for c in acted if c.name == case["expect"]]
    if len(same) != len(acted) or any(c.arguments.get("target") != wanted for c in same) or not same:
        return False
    return case["expect"] == "unwatch" or all(
        c.arguments.get("kind") == "claude_session" and until_of(c) == case["until"] for c in same)


def inbound(text: str, seat: Seat, thread: str) -> Inbound:
    return Inbound(seat.household_id, thread, text, "chat", "text", "owner", seat.person_id, False, None, "web",
                   remembers=False, taint=None)


async def one(case: dict[str, Any], seat: Seat, recorder: RecordingInference) -> RunResult:
    """One talk. A turn that raises is a failed run naming the exception type."""
    thread, error = f"watch-tools-eval-{uuid.uuid4()}", None
    try:
        *before, last = case["turns"]
        for text in before:
            await respond(inbound(text, seat, thread))
        recorder.steps.clear()
        await respond(inbound(last, seat, thread))
    except Exception as e:
        error = type(e).__name__
    steps: list[Step] = [s for s in recorder.steps if s.task == "chat"]
    calls = [c for s in steps for c in s.asked]
    await _end_watches(seat)
    return RunResult(case["id"], error is None and passes(case, calls),
                     tuple(describe(c) for c in calls if c.name in WATCH_TOOLS), tuple(c.name for c in calls),
                     repeats(steps), error)


async def _end_watches(seat: Seat) -> None:
    store = services.get(Watches)
    for w in await store.live(seat.household_id, seat.person_id):
        await store.disarm(seat.household_id, seat.person_id, w.kind, w.target)


async def run(runs: int, only: str | None, seat: Seat) -> dict[str, list[RunResult]]:
    """Each case (`only` that one) `runs` times, in order, through the wired services with the seat's person given
    the fake bridge and `Inference` recorded for the run. Raises ValueError for an unknown case."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no watch-tools case {only!r}")
    real = {Connections: services.get(Connections), Bridge: services.get(Bridge), Inference: services.get(Inference)}
    recorder = RecordingInference(services.get(Inference))
    services.register(Connections, EvalConnections(seat.household_id, seat.person_id))
    services.register(Bridge, EvalBridge())
    services.register(Inference, recorder)
    started = time.perf_counter()
    try:
        out = {c["id"]: [await one(c, seat, recorder) for _ in range(runs)] for c in cases}
    finally:
        for interface, provider in real.items():
            services.register(interface, provider)
    logs.info(log, "eval.watch_tools", cases=len(cases), runs=runs,
              passes=sum(r.passed for rs in out.values() for r in rs),
              duration_ms=int((time.perf_counter() - started) * 1000))
    return out


def render(results: dict[str, list[RunResult]]) -> str:
    """One row per case with its pass count and a total, then each run's tools and its watch calls."""
    expects = {c["id"]: c["expect"] for c in load()}
    rows = [f"{'case':36} {'expect':8} {'pass':>5} {'repeats':>7} {'errors':>6}"]
    for cid, rs in results.items():
        rows.append(f"{cid:36} {expects[cid]:8} {sum(r.passed for r in rs)}/{len(rs):<3} "
                    f"{sum(r.repeats for r in rs):>7} {sum(r.error is not None for r in rs):>6}")
    every = [r for rs in results.values() for r in rs]
    rows.append(f"{'TOTAL':36} {'':8} {sum(r.passed for r in every)}/{len(every):<3} "
                f"{sum(r.repeats for r in every):>7} {sum(r.error is not None for r in every):>6}")
    for cid, rs in results.items():
        for i, r in enumerate(rs, 1):
            rows.append(f"  {cid}#{i}: {'PASS' if r.passed else 'FAIL'} {'>'.join(r.tools) or '-'} | "
                        f"{' '.join(r.seen) or 'no watch call'}" + (f" | {r.error}" if r.error else ""))
    return "\n".join(rows)
