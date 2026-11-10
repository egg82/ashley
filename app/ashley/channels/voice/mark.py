"""What one wake tells the open screens through Live (`decisions.md`, "Open screens learn what changed through Live"):
she is `listening` from the wake until the transcript is in (or the run ends), `speaking` from handing her reply to the
room until `Playback` estimates it has ended, then `idle`. `thinking` between them is the turn loop's own
(`channels.live_turn.Showing`). A satellite is a shared channel, so the household's every screen is shown it
(`live.events.shown_for`), naming neither the room nor who spoke. One token names the wake's states."""

import asyncio
import secrets
from typing import Literal

from ... import services
from ...live.events import HerState, HerStateName, shown_for
from ...live.live import Live
from ..live_turn import AT_MOST_S
from .config import Playback


class Mark:
    def __init__(self, household_id: int, playback: Playback) -> None:
        self._shown = shown_for(False, household_id, None)
        self._playback = playback
        self._turn = secrets.token_hex(6)
        self._state: Literal["idle", "listening", "speaking"] = "idle"

    def listening(self) -> None:
        self._state = "listening"
        self._publish("listening")

    def heard(self) -> None:
        """The microphone is done with: the transcript is in, or the run ended before one."""
        if self._state == "listening":
            self._state = "idle"
            self._publish("idle")

    def speaking(self, text: str) -> None:
        """Her reply `text` was handed to the room. The idle that follows is the estimated end of its playing."""
        self._state = "speaking"
        self._publish("speaking")
        asyncio.get_running_loop().call_later(self._playback.seconds(text), self._ended)

    def _ended(self) -> None:
        self._state = "idle"
        self._publish("idle")

    def _publish(self, state: HerStateName) -> None:
        if self._shown is not None:
            services.get(Live).publish(HerState(self._shown, self._turn, state, AT_MOST_S))
