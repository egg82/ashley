"""The turn a watch's wake starts (`ashley.watches`): an `Inbound` nobody is waiting on (`unprompted`), so whether it goes
out at all is `Initiative`'s, from her `says`: set to none, nothing is posted to any thread or pushed, and she may
still act. It runs on the talk of the bench whose turn armed the watch, while that bench is open, and otherwise on the
person's phone thread (`push:<person id>`), with the person as the one it is with so the reply reaches them alone.
Whether it also reaches their phone is hers to set (`Reply.to_phone`, offered with the facts by `channels.to_phone`).
The stored message is the household's turn, written by the watch's kind from the tracked fields alone, never anything
on the source's screen; what she is to do reaches her only as the turn's `note`: the kind's, the watch's `brief`
(never logged), which wake in the series
this is and since when, and whether the watch has now ended. Its tools follow `Reminder.tools`: none named offers only
the ones that change nothing, named ones only those; a watch a hand-off armed keeps the tools of the thread she is on. The turn is tainted `watch` when its kind reads outside
text, and `inherited` when a tainted turn armed the watch (`Watch.taint`).
The wake's id is the turn's `source`, so a wake handed in twice is one turn.

Logs `watch_wake.done` with the watch id, what the wake told, whether it ran on a bench, and duration_ms;
`watch_wake.refused` and `watch_wake.malformed` with the watch id. Never a label."""

import logging
import time
from dataclasses import replace
from datetime import UTC, datetime

from ... import logs, services
from ...people.quiet import held_now
from ...senses.wakes import Outcome, WatchWake
from ...watches.config import CONFIG
from ...watches.model import Watch
from ...watches.registry import KINDS
from ...watches.rows import changes_of
from ...watches.watches import Watches
from ...workshop.model import Owner, thread_of
from ...workshop.workshop import Workshop
from ..model import Inbound, Taint
from ..respond import RespondRefused, respond

log = logging.getLogger("ashley.channels.wake")

PAUSED_NOTE = ("A watch you keep could not read its source several times in a row and is paused; it checks again "
               "and goes on if the source answers. The message names it and why. Tell the person if they would want "
               "to know. With `says` none nothing is posted or pushed to anyone.")


def said(watch: Watch, wake: WatchWake) -> str:
    """The wake as the page shows it, from the watch's fields alone."""
    if wake.what == "paused":
        return f"Watch {watch.label}: paused, {wake.changes.get('reason')}"
    return KINDS.get(watch.kind).said(watch, changes_of(wake.changes))


def note(watch: Watch, wake: WatchWake, detail: str = "") -> str:
    """What only she reads with the turn; `detail` is what the kind fetched for it (`Kind.detail`)."""
    if wake.what == "paused":
        return PAUSED_NOTE
    changes = changes_of(wake.changes)
    ended = " The watch has now ended, so you are not woken by it again." if wake.changes.get("ended") else ""
    why = "" if watch.brief is None else f"\nWhat this watch is for, as it was set up: {watch.brief}"
    more = f"\n{detail}" if detail else ""
    return (f"{KINDS.get(watch.kind).note(watch, changes)}{more}{why}\nThis is wake {wake.changes.get('series')} of this watch, "
            f"covering everything since {wake.changes.get('since')}.{ended}")


def inbound(wake_id: int, watch: Watch, wake: WatchWake, on_bench: bool, detail: str = "",
            quiet: bool = False) -> Inbound:
    """The turn for `wake`: on its bench's talk when `on_bench`, else on the person's phone thread, where `quiet` (their
    own quiet hours hold) keeps it from reaching them; a bench they have open is never held. Raises ValueError for
    a changed wake whose stored changes cannot be read."""
    phone_thread = Inbound(household_id=watch.household_id, thread=f"push:{watch.person_id}", text=said(watch, wake),
                           kind="chat", medium="text", audience="owner", speaker_id=watch.person_id, shared=False,
                           place=None, channel="device", remembers=False, later=True, later_by="outbox",
                           source=f"wake:{wake_id}", unprompted=True, author="household", note=note(watch, wake, detail),
                           tools_only=None if watch.armed_by == "handoff" else watch.tools,
                           reads_only=watch.armed_by != "handoff" and watch.tools is None,
                           taint=_taint(watch), made_in=watch.made_in, quiet=quiet and not on_bench)
    if not on_bench or watch.bench_id is None:
        return phone_thread
    return replace(phone_thread, thread=thread_of(watch.bench_id), kind="brainstorm", channel="web", remembers=True,
                   later_by="turn", bench_id=watch.bench_id, on_page=True)


def _taint(watch: Watch) -> Taint | None:
    """`watch` when its kind reads outside text, `inherited` when a tainted turn armed it, else None."""
    if KINDS.get(watch.kind).outside:
        return "watch"
    return None if watch.taint is None else "inherited"


async def fired(wake_id: int, wake: WatchWake, age_s: float) -> Outcome:
    """What came of it: `turn`, `expired` past `wake_max_age_s`, `cancelled` when the watch is gone, `failed` when the
    model refused it or its changes cannot be read. Raises WatchesUnavailable, WorkshopUnavailable, PeopleUnavailable and
    RespondUnavailable, which leave it due."""
    if age_s > CONFIG.wake_max_age_s:
        return "expired"
    watch = await services.get(Watches).get(wake.watch_id)
    if watch is None:
        return "cancelled"
    started = time.perf_counter()
    on_bench = await _open(watch)
    try:
        turn = inbound(wake_id, watch, wake, on_bench, await KINDS.get(watch.kind).detail(watch),
                       await held_now(watch.household_id, watch.person_id, datetime.now(UTC)))
    except ValueError:
        logs.warning(log, "watch_wake.malformed", watch=watch.id)
        return "failed"
    try:
        await respond(turn)
    except RespondRefused:
        logs.warning(log, "watch_wake.refused", watch=watch.id)
        return "failed"
    logs.info(log, "watch_wake.done", watch=watch.id, what=wake.what, bench=on_bench,
              duration_ms=int((time.perf_counter() - started) * 1000))
    return "turn"


async def _open(watch: Watch) -> bool:
    """Whether the bench is one of the person's open ones. Raises WorkshopUnavailable."""
    if watch.bench_id is None:
        return False
    benches = await services.get(Workshop).open_benches(Owner(watch.household_id, watch.person_id))
    return any(b.id == watch.bench_id for b in benches)
