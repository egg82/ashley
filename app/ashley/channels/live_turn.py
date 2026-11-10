"""What one turn tells the open screens (`ashley.live.live.Live`): her state while it runs, and that a turn was stored on
a personal thread. Who may be shown it is `ashley.live.events.shown_for` of the channel: an `owner` channel's turn is
its person's alone; a shared channel's is the household's, and names neither the room nor who is talking. A shared
channel's stored turns are announced only to the screen of the device that has one (`Inbound.device_id`), never to a
person's."""

import secrets
import time

from .. import services
from ..live import live
from ..live.events import FailedWhy, HerState, HerStateName, Shown, ThreadTurn, TurnFailed, shown_for
from ..live.live import Live
from .model import Inbound

AT_MOST_S = live.load().thinking_at_most_s


class Showing:
    """One turn as the screens see it, named by a random token, or by `turn` when another runner began it."""

    def __init__(self, inbound: Inbound, turn: str | None = None) -> None:
        self._owner_only = inbound.audience == "owner"
        self._shown = shown_for(self._owner_only, inbound.household_id, inbound.speaker_id)
        self._thread = inbound.thread
        self._screen = (Shown(inbound.household_id, None, inbound.device_id)
                        if inbound.device_id is not None and not self._owner_only else None)
        self._turn = turn or secrets.token_hex(6)
        self._told = time.monotonic()

    @property
    def turn(self) -> str:
        """The token naming this turn on the screens."""
        return self._turn

    def state(self, state: HerStateName) -> None:
        """She is now `state` in this turn."""
        self._told = time.monotonic()
        if self._shown is not None:
            services.get(Live).publish(HerState(self._shown, self._turn, state, AT_MOST_S))

    def still_working(self) -> None:
        """She is still thinking in this turn: told again once half of what a screen believes it for has passed, so a
        turn longer than that is not shown idle while it works."""
        if time.monotonic() - self._told >= AT_MOST_S / 2:
            self.state("thinking")

    def stored(self, thread: str | None = None) -> None:
        """A turn of this one's was stored on its thread, or on `thread` (the bench's talk it continued on)."""
        thread = self._thread if thread is None else thread
        if self._shown is not None and self._owner_only:
            services.get(Live).publish(ThreadTurn(self._shown, thread))
        elif self._screen is not None:
            services.get(Live).publish(ThreadTurn(self._screen, thread))

    def failed(self, why: FailedWhy) -> None:
        """This turn has no reply after its request had returned pending, or is kept to try again (`retrying`); shown
        where `stored` is."""
        if self._shown is not None and self._owner_only:
            services.get(Live).publish(TurnFailed(self._shown, self._thread, why))
        elif self._screen is not None:
            services.get(Live).publish(TurnFailed(self._screen, self._thread, why))
