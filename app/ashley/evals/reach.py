"""The reach eval against the live model: which of her tools she reaches for. Each case in `reach_cases.json` is an ask put
through her real turn loop (`channels.respond`, a chat on the web channel, with every tool a turn there offers), `runs`
times, and names the tool `groups` (the sources `prompt-sizes` reports: `reminders`, `money`, `mail`...) and the
`tools` a correct answer calls; a case naming neither is an ask that needs no tool, and passes only when she calls none.
A run passes when every named group has a call in it and every named tool was called, and, for a case with `any_of`, when
one of its alternatives (each a list of group or tool names) was reached whole: an ask more than one route answers
correctly, such as a reader's delegation or the same sources read directly. `why` says why a case reads as it does. The groups and tools she called
beyond those are reported as `extra`, which is how a no-tool ask that reaches for one shows. A group or tool no catalogue
held in the run is in `unoffered`: a typo in the case, or something the household does not have.

Nothing a call would change reaches outside: `reach_guard.ReachGuard` answers every call whose spec does not say it only
reads (`ToolSpec.reads`) as done, for every source of the turn, and those it kept are in `refused`. The reads reach
their service, so the household asked as must be a scratch copy's. Run under `--variant` with a group cut, the cases that
need it fail: that is the regression on-demand tools must not cause.

Under a variant with a `core`, a group she has not loaded is not offered: the loader (`use_tools`) is neither a group nor
a tool she called, so it is never `extra` and a no-tool ask that only calls it passes, but its steps count and the groups
she loaded are reported (`loaded`).

Per run: steps (rounds of tool calls), whether the step limit was reached, the tool names in order, her main calls' input
tokens per step from the spend ledger and the models that answered. Logs `eval.reach` once per run of the eval: cases,
runs, passes, extra groups called and duration_ms. Never a case's ask or reply, or a tool's arguments or results."""

import json
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .. import logs, services
from ..channels import on_demand, turn_tools
from ..channels.model import Inbound
from ..channels.respond import respond
from ..inference.inference import Inference
from ..tools.tools import Tools
from .house import Ledger, Seat, repeats
from .house_guard import RecordingInference, Step
from .prompt_sizes import UNOWNED
from .reach_guard import Notes, ReachGuard

log = logging.getLogger("ashley.evals")

CASES = Path(__file__).parent / "reach_cases.json"
CASE_KEYS = {"id", "ask", "groups", "tools"}
OPTIONAL_KEYS = {"any_of", "why"}
_NAMES = TypeAdapter(list[str])


@dataclass(frozen=True)
class RunResult:
    case_id: str
    passed: bool
    steps: int
    limit_hit: bool
    tools: tuple[str, ...]
    groups: tuple[str, ...]
    loaded: tuple[str, ...]
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    unoffered: tuple[str, ...]
    tokens: tuple[int, ...]
    models: tuple[str, ...]
    latency_ms: int
    refused: tuple[str, ...]
    repeats: int
    error: str | None


def _names(case: dict[str, Any], key: str) -> list[str]:
    try:
        names = _NAMES.validate_python(case[key])
    except ValidationError as e:
        raise ValueError(f"reach case {case['id']!r}: {key} is a list of distinct names") from e
    if not all(n.strip() for n in names) or len(set(names)) != len(names):
        raise ValueError(f"reach case {case['id']!r}: {key} is a list of distinct names")
    return names


def alternatives(case: dict[str, Any]) -> list[list[str]]:
    """The case's `any_of`: two or more distinct alternatives, each a list of distinct names; none when it has no `any_of`."""
    if "any_of" not in case:
        return []
    try:
        found = TypeAdapter(list[list[str]]).validate_python(case["any_of"])
    except ValidationError as e:
        raise ValueError(f"reach case {case['id']!r}: any_of is a list of lists of names") from e
    if len(found) < 2 or any(not a or len(set(a)) != len(a) or not all(n.strip() for n in a) for a in found) \
            or len({tuple(a) for a in found}) != len(found):
        raise ValueError(f"reach case {case['id']!r}: any_of is two or more distinct lists of distinct names")
    return found


def validate(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`cases` when each has `id`, `ask`, `groups` and `tools`, may have `any_of` (two or more alternatives, each a list of
    distinct names) and `why` (text), and the ids are distinct. Raises ValueError naming the case that is not."""
    seen: set[str] = set()
    for case in cases:
        name = case.get("id")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError(f"reach case id {name!r} is missing or repeated")
        seen.add(name)
        if not CASE_KEYS <= set(case) <= CASE_KEYS | OPTIONAL_KEYS:
            raise ValueError(f"reach case {name!r} has {sorted(CASE_KEYS)} and may have {sorted(OPTIONAL_KEYS)}")
        if "why" in case and not (isinstance(case["why"], str) and case["why"].strip()):
            raise ValueError(f"reach case {name!r} has a why that is text")
        if not isinstance(case["ask"], str) or not case["ask"].strip():
            raise ValueError(f"reach case {name!r} has an ask")
        _names(case, "groups")
        _names(case, "tools")
        alternatives(case)
    return cases


def load() -> list[dict[str, Any]]:
    return validate(json.loads(CASES.read_text())["cases"])


def inbound(case: dict[str, Any], seat: Seat) -> Inbound:
    """The ask as the owner's web chat sends it, offering the benches and page tools that chat offers."""
    return Inbound(seat.household_id, f"reach-eval-{uuid.uuid4()}", case["ask"], "chat", "text", "owner", seat.person_id,
                   False, None, "web", remembers=False, opens_benches=True, on_page=True, taint=None)


def needed(case: dict[str, Any], offered: dict[str, str]) -> set[str]:
    """The groups the case wants: its own, those that offered its tools and those named by any `any_of` alternative."""
    names = [*case["tools"], *(n for a in alternatives(case) for n in a)]
    return {*case["groups"], *(offered.get(n, n) for n in names)}


def lacking(case: dict[str, Any], tools: Sequence[str], groups: Sequence[str]) -> list[str]:
    """What a run that called `tools`, reaching `groups`, still lacks of the case: its groups and tools not reached and,
    when no `any_of` alternative was reached whole, the names the nearest alternative lacks."""
    missing = [g for g in case["groups"] if g not in groups] + [t for t in case["tools"] if t not in tools]
    options = [[n for n in a if n not in groups and n not in tools] for a in alternatives(case)]
    return missing + (min(options, key=len) if options and all(options) else [])


def score(case: dict[str, Any], called: list[str], offered: dict[str, str]) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """(passed, missing, extra) for a run that called `called`, in order: `missing` the groups and tools the case wanted
    that no call reached, `extra` the groups called that it did not want, in the order first called. A case wanting
    nothing passes only with no call."""
    groups = list(dict.fromkeys(offered.get(n, UNOWNED) for n in called))
    missing = lacking(case, called, groups)
    wanted = needed(case, offered)
    extra = tuple(g for g in groups if g not in wanted)
    return (not called if not wanted and not case["tools"] else not missing), tuple(missing), extra


def unoffered(case: dict[str, Any], offered: dict[str, str]) -> tuple[str, ...]:
    held = set(offered.values())
    return tuple([g for g in case["groups"] if g not in held] + [t for t in case["tools"] if t not in offered])


def loaded_groups(steps: Sequence[Step], offered: set[str]) -> tuple[str, ...]:
    """The groups she asked the loader for, in the order first asked, that the turn's tools held. The loader is neither
    a group nor a tool call of the case: it is how a group reaches her."""
    asked = [g for s in steps for c in s.asked if c.name == on_demand.LOADER for g in on_demand.named(c.arguments)]
    return tuple(g for g in dict.fromkeys(asked) if g in offered)


async def one(case: dict[str, Any], seat: Seat, ledger: Ledger, notes: Notes, recorder: RecordingInference) -> RunResult:
    """One ask. A turn that raises is a failed run naming the exception type."""
    notes.refused.clear()
    recorder.steps.clear()
    ask = inbound(case, seat)
    started = time.perf_counter()
    error, conversation = None, None
    try:
        conversation = (await respond(ask)).conversation_id
    except Exception as e:
        error = type(e).__name__
    latency = int((time.perf_counter() - started) * 1000)
    steps: list[Step] = [s for s in recorder.steps if s.task == ask.kind]
    billed = [] if conversation is None else await ledger(conversation, ask.kind)
    called = [c.name for s in steps for c in s.asked if c.name != on_demand.LOADER]
    passed, missing, extra = score(case, called, notes.offered)
    loaded = loaded_groups(steps, set(notes.offered.values()))
    return RunResult(case["id"], error is None and passed, sum(bool(s.asked) for s in steps),
                     any(s.choice == "none" for s in steps), tuple(called),
                     tuple(dict.fromkeys(notes.offered.get(n, UNOWNED) for n in called)), loaded, missing, extra,
                     unoffered(case, notes.offered), tuple(b.tokens for b in billed),
                     tuple(sorted({f"{b.provider}/{b.model}" for b in billed})), latency,
                     tuple(a.name for a in notes.refused), repeats(steps), error)


async def run(runs: int, only: str | None, seat: Seat, ledger: Ledger) -> dict[str, list[RunResult]]:
    """Each case (`only` that one) `runs` times, in order, through the wired services with every turn's tools guarded
    (`ReachGuard`) and `Inference` recorded for the run. Raises ValueError for an unknown case."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no reach case {only!r}")
    real_for_turn, real_inference = turn_tools.for_turn, services.get(Inference)
    notes = Notes()
    recorder = RecordingInference(real_inference)

    def guarded(*args: Any, **kwargs: Any) -> Tools:
        return ReachGuard(real_for_turn(*args, **kwargs), notes=notes)

    turn_tools.for_turn = guarded
    services.register(Inference, recorder)
    started = time.perf_counter()
    try:
        out = {c["id"]: [await one(c, seat, ledger, notes, recorder) for _ in range(runs)] for c in cases}
    finally:
        turn_tools.for_turn = real_for_turn
        services.register(Inference, real_inference)
    results = [r for rs in out.values() for r in rs]
    logs.info(log, "eval.reach", cases=len(cases), runs=runs, passes=sum(r.passed for r in results),
              extra=sum(len(r.extra) for r in results), refused=sum(len(r.refused) for r in results),
              duration_ms=int((time.perf_counter() - started) * 1000))
    return out
