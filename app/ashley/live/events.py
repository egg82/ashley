"""What Live carries: small typed events of ids and states, never text, people's data, a room or who is talking. Each
names who may be shown it (`Shown`), decided once by `shown_for` from whose channel it came from, and checked for each
screen by `shown_to`."""

import json
from dataclasses import dataclass
from typing import Any, Literal, get_args

HerStateName = Literal["listening", "thinking", "speaking", "idle"]
PageRoom = Literal["her", "workshop", "memory", "devices", "connections"]
"""The rooms of a person's page, as the client names them."""
ChangedBy = Literal["her", "person"]
"""Who made the command behind a `BenchChanged`."""


@dataclass(frozen=True)
class Shown:
    """Who may be shown an event: of `household_id`, everyone (a person's screen or a device's) when both ids are None;
    `person_id`'s screens alone when it is set; `device_id`'s screen alone when that is set, which no person's screen
    is. Never both."""

    household_id: int
    person_id: int | None
    device_id: int | None = None

    def __post_init__(self) -> None:
        if self.person_id is not None and self.device_id is not None:
            raise ValueError("an event is shown to a person or to a device, not both")


@dataclass(frozen=True)
class Viewer:
    """A signed-in person with a screen open."""

    household_id: int
    person_id: int


@dataclass(frozen=True)
class DeviceViewer:
    """A shared device's screen (the hallway kiosk) signed in as the device."""

    household_id: int
    device_id: int


@dataclass(frozen=True)
class HerState:
    """Her state in one turn. `turn` is a random token naming the turn and nothing else, so a screen can tell two turns
    apart; `at_most_s` is how long a screen may show a state that is not `idle` before treating the turn as over,
    since the `idle` can be lost with the pod that ran it."""

    shown: Shown
    turn: str
    state: HerStateName
    at_most_s: float


@dataclass(frozen=True)
class ThreadTurn:
    """A turn was stored on `thread`, so a page showing it refetches. Shown to the thread's owner alone: its person, or
    its device."""

    shown: Shown
    thread: str

    def __post_init__(self) -> None:
        if self.shown.person_id is None and self.shown.device_id is None:
            raise ValueError("a thread's turn is shown to its owner only")


FailedWhy = Literal["unavailable", "refused", "retrying", "unfinished", "too_big"]
"""Why a turn has no reply, as the request that asked would have said: she could not answer (`unavailable`), she declined
(`refused`), it failed and its work is kept to try again (`retrying`, shown until a reply lands), it failed with
nothing she could say (`unfinished`), or the work was too big for one reply and is not tried again (`too_big`). The page words each; code writes none of them as her turn."""


@dataclass(frozen=True)
class TurnFailed:
    """A turn on `thread` ended with no reply of hers, after the request that asked for it had already returned (her
    turn was being worked on elsewhere), so a page showing the thread shows the person's message as unanswered. Shown
    to the thread's owner alone: its person, or its device."""

    shown: Shown
    thread: str
    why: FailedWhy

    def __post_init__(self) -> None:
        if self.shown.person_id is None and self.shown.device_id is None:
            raise ValueError("a thread's failed turn is shown to its owner only")


@dataclass(frozen=True)
class BenchChanged:
    """Command `seq` changed bench `bench_id`, so a page showing the bench reads it back; `seq` 0 is no command but a
    site on the bench newly measured (`api.bench_frames`). `by` is who made the command, None when it was no one's
    (a measurement, or a change carried out after the command). Shown to the bench's owner alone."""

    shown: Shown
    bench_id: int
    seq: int
    by: ChangedBy | None = None

    def __post_init__(self) -> None:
        if self.shown.person_id is None:
            raise ValueError("a bench's change is shown to its owner only")


CueName = Literal["play", "pause", "seek"]


@dataclass(frozen=True)
class BenchCued:
    """She cued the player of video piece `piece_id` on bench `bench_id` (`action`, and `seconds` for a seek). Shown to
    the bench's owner alone, to the screens open now: nothing keeps it for a screen that opens later, and it is not a
    change of the bench."""

    shown: Shown
    bench_id: int
    piece_id: int
    action: CueName
    seconds: float | None

    def __post_init__(self) -> None:
        if self.shown.person_id is None:
            raise ValueError("a bench's cue is shown to its owner only")


@dataclass(frozen=True)
class PageMoved:
    """She moved the person's page to `room`, and within the workshop to bench `bench_id` when it is set. Shown to that
    person's own screens alone, each of which decides for itself whether to follow now."""

    shown: Shown
    room: PageRoom
    bench_id: int | None = None

    def __post_init__(self) -> None:
        if self.shown.person_id is None:
            raise ValueError("a page is moved for its person only")
        if self.bench_id is not None and self.room != "workshop":
            raise ValueError("a bench is in the workshop")


@dataclass(frozen=True)
class ScreenChanged:
    """Command `seq` changed device `device_id`'s screen (its layout, its buttons), or the screen was laid out for the
    first time. Shown to every screen of the household, a person's and a device's: the tablet reloads its layout when
    `device_id` is its own and the Devices room that device's buttons. It carries ids only; `shown` is the household's,
    its `device_id` is not the screen's."""

    shown: Shown
    device_id: int
    seq: int

    def __post_init__(self) -> None:
        if self.shown.person_id is not None or self.shown.device_id is not None:
            raise ValueError("a screen's change is shown to the whole household")


@dataclass(frozen=True)
class Announced:
    """She announced something to this screen: it plays the clip `clip` names and shows its line
    (`ashley.channels.voice.clips.Clips`). `clip` is the clip's token, its only credential, short-lived and never
    logged, which is why the event goes to one person's screens or one device's alone, never the household's."""

    shown: Shown
    clip: str

    def __post_init__(self) -> None:
        if self.shown.person_id is None and self.shown.device_id is None:
            raise ValueError("an announcement is shown to one person or one device")


Event = HerState | ThreadTurn | TurnFailed | BenchChanged | BenchCued | PageMoved | ScreenChanged | Announced
Watcher = Viewer | DeviceViewer


def shown_for(owner_only: bool, household_id: int, person_id: int | None) -> Shown | None:
    """The privacy rule. What happens on a channel only its owner hears (`owner_only`: a DM, the person's web chat) is
    shown to that person only; on a shared one (satellites, a shared Discord channel, devices) to every screen of the
    household. None, shown to no one, for an owner's channel that names no person."""
    if owner_only:
        return None if person_id is None else Shown(household_id, person_id)
    return Shown(household_id, None)


def shown_to(event: Event, viewer: Watcher) -> bool:
    """Whether `viewer` may be shown `event`: only its own household's. A person's screen is shown the household's
    shared events and their own, never a device's. A device's screen is shown the shared events and its own thread's,
    never an event of any person's channel (an owner's)."""
    shown = event.shown
    if shown.household_id != viewer.household_id:
        return False
    if isinstance(viewer, DeviceViewer):
        return shown.person_id is None and shown.device_id in (None, viewer.device_id)
    return shown.device_id is None and shown.person_id in (None, viewer.person_id)


def encode(event: Event) -> str:
    """The event as one JSON object, for the wire between pods."""
    base: dict[str, Any] = {"household_id": event.shown.household_id, "person_id": event.shown.person_id,
                            "device_id": event.shown.device_id}
    if isinstance(event, HerState):
        return json.dumps({**base, "type": "state", "turn": event.turn, "state": event.state,
                           "at_most_s": event.at_most_s})
    if isinstance(event, BenchChanged):
        return json.dumps({**base, "type": "bench", "bench_id": event.bench_id, "seq": event.seq, "by": event.by})
    if isinstance(event, BenchCued):
        return json.dumps({**base, "type": "cue", "bench_id": event.bench_id, "piece_id": event.piece_id,
                           "action": event.action, "seconds": event.seconds})
    if isinstance(event, ScreenChanged):
        return json.dumps({**base, "type": "screen", "screen": event.device_id, "seq": event.seq})
    if isinstance(event, PageMoved):
        return json.dumps({**base, "type": "page", "room": event.room, "bench_id": event.bench_id})
    if isinstance(event, TurnFailed):
        return json.dumps({**base, "type": "failed", "thread": event.thread, "why": event.why})
    if isinstance(event, Announced):
        return json.dumps({**base, "type": "announce", "clip": event.clip})
    return json.dumps({**base, "type": "turn", "thread": event.thread})


def decode(payload: str) -> Event | None:
    """What `encode` wrote; None for anything else, so a malformed payload is skipped rather than raised."""
    try:
        raw = json.loads(payload)
        shown = Shown(int(raw["household_id"]), None if raw["person_id"] is None else int(raw["person_id"]),
                      None if raw.get("device_id") is None else int(raw["device_id"]))
        if raw["type"] == "state" and raw["state"] in get_args(HerStateName):
            return HerState(shown, str(raw["turn"]), raw["state"], float(raw["at_most_s"]))
        if raw["type"] == "turn":
            return ThreadTurn(shown, str(raw["thread"]))
        if raw["type"] == "failed" and raw["why"] in get_args(FailedWhy):
            return TurnFailed(shown, str(raw["thread"]), raw["why"])
        if raw["type"] == "bench":
            by = raw.get("by")
            return BenchChanged(shown, int(raw["bench_id"]), int(raw["seq"]), by if by in get_args(ChangedBy) else None)
        if raw["type"] == "cue" and raw["action"] in get_args(CueName):
            return BenchCued(shown, int(raw["bench_id"]), int(raw["piece_id"]), raw["action"],
                             None if raw["seconds"] is None else float(raw["seconds"]))
        if raw["type"] == "screen":
            return ScreenChanged(shown, int(raw["screen"]), int(raw["seq"]))
        if raw["type"] == "announce":
            return Announced(shown, str(raw["clip"]))
        if raw["type"] == "page" and raw["room"] in get_args(PageRoom):
            return PageMoved(shown, raw["room"], None if raw["bench_id"] is None else int(raw["bench_id"]))
    except (ValueError, KeyError, TypeError):
        return None
    return None
