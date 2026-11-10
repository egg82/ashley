"""The tidy pass, run after a bench turn: when a text piece of the bench is not as the last finished pass saw it, a cheap
model (task `bench_tidy`) points at passages that have gone wrong, and what stands is kept for her next turn
(`offer.to_check`). It runs apart from the turn, which never waits on it.

A pass is due when any text piece's version differs from the one the last finished pass recorded, so a turn that moved or
resized pieces, or changed none, asks nothing of the model. One pass holds a bench at a time (`Tidy.begin`), on any pod of
either site; the versions are recorded only when a pass finishes, so a pass lost to a restart, a busy model or a
pass already running is made up by the next turn's end and costs nothing else.
A pass whose every route rejected the request is recorded finished with no findings: asking again replays the rejection.

Logs `tidy.pass` with the bench id, outcome (`unchanged`, `busy`, `ok`, `unavailable`, `refused`, `rejected`, `bench_gone`), the pieces
sent, the findings kept per kind, the findings dropped and duration_ms. Never a quote, a reason or a piece's text."""

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any

from .. import logs, services
from ..inference.inference import Inference, InferenceRefused, InferenceRejected, InferenceUnavailable
from ..inference.model import Task
from ..workshop.model import Owner, Piece
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from . import config as tidy_config
from .pointer import Pointed, ask, check
from .tidy import Tidy, TidyUnavailable

log = logging.getLogger("ashley.tidy")
CONFIG = tidy_config.load()
TASK: Task = "bench_tidy"
_running: set[asyncio.Task[None]] = set()


def start(owner: Owner, bench_id: int) -> None:
    """`after_turn` on its own task; the set keeps the task alive until it ends (asyncio holds tasks only weakly)."""
    _hold(after_turn(owner, bench_id))


def _hold(work: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(work)
    _running.add(task)
    task.add_done_callback(_running.discard)


def versions_of(pieces: tuple[Piece, ...] | list[Piece]) -> dict[int, int]:
    """The version of each of the bench's pieces of a kind the pass reads."""
    return {p.id: p.version for p in pieces if p.kind in CONFIG.kinds}


async def after_turn(owner: Owner, bench_id: int) -> None:
    """One pass if one is due, logged `tidy.pass`. Never raises for what the bench, the record or the model did."""
    started = time.monotonic()
    outcome, sent, kept, dropped = "unavailable", 0, "", 0
    try:
        outcome, sent, kept, dropped = await _pass(owner, bench_id)
    except (TidyUnavailable, WorkshopUnavailable):
        pass
    except BenchNotFound:
        outcome = "bench_gone"
    logs.info(log, "tidy.pass", bench=bench_id, outcome=outcome, pieces=sent, found=kept or "none", dropped=dropped,
              duration_ms=round((time.monotonic() - started) * 1000))


async def _pass(owner: Owner, bench_id: int) -> tuple[str, int, str, int]:
    tidy = services.get(Tidy)
    seen = await tidy.checked(bench_id)
    view = await services.get(Workshop).read(owner, bench_id)
    now = versions_of(view.pieces)
    if view.bench.closed_at is not None or not any(seen.get(i) != v for i, v in now.items()):
        return "unchanged", 0, "", 0
    asked = ask(view.pieces, CONFIG)
    if asked is None or not await tidy.begin(owner.household_id, bench_id, CONFIG.lock_s):
        return ("unchanged" if asked is None else "busy"), 0, "", 0
    try:
        pointed = await services.get(Inference).generate(TASK, asked.prompt, Pointed)
    except InferenceRejected:
        await tidy.finish(owner.household_id, bench_id, now, (), CONFIG.keep_s)
        return "rejected", len(asked.seen), "", 0
    except (InferenceUnavailable, InferenceRefused) as e:
        await tidy.release(bench_id)
        return ("refused" if isinstance(e, InferenceRefused) else "unavailable"), len(asked.seen), "", 0
    except BaseException:
        await tidy.release(bench_id)
        raise
    checked = check(pointed, asked.seen, CONFIG)
    await tidy.finish(owner.household_id, bench_id, now, checked.found, CONFIG.keep_s)
    per = checked.per_kind()
    return "ok", len(asked.seen), ",".join(f"{k}={n}" for k, n in sorted(per.items())), checked.dropped
