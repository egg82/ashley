"""The watches job: the singleton that checks due watches and records what it finds (`decisions.md`, "Watches wake her
when what a read returns changes, until a condition or a time"). It runs under the lease, so on one site at a time, and
never waits on a turn: a wake is a row the wakes runner takes up.

Logs, while anything was due or ended, `watches.tick` (`expired`, `pruned`, `due`, `baselines`, `quiet`, `woke`,
`failed`, `paused`, `resumed`, `ended`, `later`, `lost` the checks another holder recorded first, `duration_ms`);
`watches.woke` (watch id, series, counts of new, changed and gone items); `watches.paused` and `watches.resumed`
(watch id, reason, failures); `watches.ended` (watch id, reason); `watches.read_failed` (kind, reason, how many
watches); `watches.unavailable` once per run of failed ticks. Never a target, label or value."""

import asyncio
import logging
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping

from .. import logs, services
from .config import CONFIG, WatchesConfig
from .judge import judge
from .kinds import Kind, Registry
from .model import Baseline, Check, Failed, Later, Quiet, Read, ReadFailed, Watch, Woke
from .registry import KINDS
from .watches import Watches, WatchesUnavailable

log = logging.getLogger("ashley.watches")

NAME = "watches"

Group = tuple[str, int, int]


async def run(config: WatchesConfig = CONFIG, kinds: Registry = KINDS,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Tick every `tick_s`, or sooner when a kind's `hold` nudges, until cancelled; each kind's `hold` runs alongside."""
    nudged = asyncio.Event()
    async with asyncio.TaskGroup() as held:
        for kind in kinds.all():
            held.create_task(kind.hold(nudged.set))
        await _ticks(config, kinds, sleep, nudged)


async def _ticks(config: WatchesConfig, kinds: Registry, sleep: Callable[[float], Awaitable[None]],
                 nudged: asyncio.Event) -> None:
    failing = False
    while True:
        nudged.clear()
        try:
            await tick(config, kinds)
        except WatchesUnavailable:
            if not failing:
                logs.warning(log, "watches.unavailable")
            failing = True
        else:
            failing = False
        await _pause(sleep, config.tick_s, nudged)


async def _pause(sleep: Callable[[float], Awaitable[None]], seconds: float, nudged: asyncio.Event) -> None:
    """`sleep(seconds)`, cut short by a nudge; what `sleep` raises is raised."""
    if nudged.is_set():
        return
    napping, nudge = asyncio.ensure_future(sleep(seconds)), asyncio.ensure_future(nudged.wait())
    try:
        await asyncio.wait((napping, nudge), return_when=asyncio.FIRST_COMPLETED)
    finally:
        nudge.cancel()
        if not napping.done():
            napping.cancel()
    if napping.done() and not nudge.done():
        await napping


async def tick(config: WatchesConfig = CONFIG, kinds: Registry = KINDS) -> Counter[str]:
    """One tick: expire and prune, then check the due watches, one read per kind, household and person. Raises
    WatchesUnavailable."""
    started = time.perf_counter()
    store = services.get(Watches)
    gone = await store.expire(config.keep_s)
    counts: Counter[str] = Counter(expired=gone.expired, pruned=gone.pruned)
    due = await store.due(config.batch)
    counts["due"] = len(due)
    groups: dict[Group, list[Watch]] = defaultdict(list)
    for watch in due:
        groups[(watch.kind, watch.household_id, watch.person_id)].append(watch)
    for (kind, _, _), group in groups.items():
        reads = await _read(kinds.get(kind), kind, group, config.read_timeout_s)
        for watch in group:
            await _record(store, watch, judge(reads.get(watch.id, ReadFailed("bad_result")), watch), config, counts)
    if counts["due"] or counts["expired"] or counts["pruned"]:
        logs.info(log, "watches.tick", **{k: counts[k] for k in _TICK}, duration_ms=int((time.perf_counter() - started) * 1000))
    return counts


_TICK = ("expired", "pruned", "due", "baselines", "quiet", "woke", "failed", "paused", "resumed", "ended", "later", "lost")


async def _read(kind: Kind, name: str, group: list[Watch], timeout_s: float) -> Mapping[int, Read]:
    """The group's reads; a kind that raises or outlasts `timeout_s` fails every watch in the group `unreachable`."""
    try:
        reads = await asyncio.wait_for(kind.read(group), timeout_s)
    except Exception:
        reads = {w.id: ReadFailed("unreachable") for w in group}
    for reason in sorted({r.reason for r in reads.values() if isinstance(r, ReadFailed)}):
        count = sum(1 for r in reads.values() if isinstance(r, ReadFailed) and r.reason == reason)
        logs.warning(log, "watches.read_failed", kind=name, reason=reason, watches=count)
    return reads


async def _record(store: Watches, watch: Watch, check: Check, config: WatchesConfig, counts: Counter[str]) -> None:
    if not await store.record(watch.id, watch.version, check):
        counts["lost"] += 1
        return
    counts[_OUTCOME[type(check)]] += 1
    if isinstance(check, Later):
        return
    if isinstance(check, Failed):
        _failed(watch, check, config, counts)
        return
    if watch.state == "paused":
        counts["resumed"] += 1
        logs.info(log, "watches.resumed", watch=watch.id, reason=watch.reason, failures=watch.failures)
    if isinstance(check, Woke):
        changed = Counter(c.kind for c in check.changes)
        logs.info(log, "watches.woke", watch=watch.id, series=watch.series + 1, new=changed["new"],
                  changed=changed["changed"], gone=changed["gone"])
    if isinstance(check, (Quiet, Woke)) and check.ends:
        counts["ended"] += 1
        logs.info(log, "watches.ended", watch=watch.id, reason="until")


def _failed(watch: Watch, check: Failed, config: WatchesConfig, counts: Counter[str]) -> None:
    if watch.state == "armed" and watch.failures + 1 >= config.fail_after:
        counts["paused"] += 1
        logs.warning(log, "watches.paused", watch=watch.id, reason=check.reason, failures=watch.failures + 1)


_OUTCOME: dict[type, str] = {Baseline: "baselines", Quiet: "quiet", Woke: "woke", Failed: "failed", Later: "later"}
