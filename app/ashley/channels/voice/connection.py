"""One satellite's ESPHome native API session, narrowed to what the voice adapter uses. `Connection` is the seam a test
fakes; `EsphomeConnection` is it over `aioesphomeapi.APIClient` (the client Home Assistant itself uses), encrypted with
the Noise pre-shared key."""

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol

from aioesphomeapi.client import APIClient
from aioesphomeapi.model import (EntityState, MediaPlayerCommand, MediaPlayerEntityState, MediaPlayerInfo,
                                 MediaPlayerState, VoiceAssistantAudioSettings, VoiceAssistantEventType)

from ..model import Satellite

PORT = 6053

OnStart = Callable[[], Coroutine[Any, Any, None]]
"""The device heard its wake word and is about to stream the microphone."""
OnAudio = Callable[[bytes], Coroutine[Any, Any, None]]
"""One chunk of 16 kHz 16-bit mono PCM from the microphone."""
OnStop = Callable[[bool], Coroutine[Any, Any, None]]
"""The microphone stopped: `True` when the device aborted the run, `False` when its audio simply ended."""


class Link(Protocol):
    """What a run uses to talk back to its satellite."""

    def send_event(self, event: VoiceAssistantEventType, data: dict[str, str] | None) -> None:
        """Send one voice-assistant pipeline event, with its data fields, as Home Assistant would."""
        ...


class Announcer(Protocol):
    """What a reply said outside a wake uses to reach its satellite."""

    def announce(self, url: str) -> bool:
        """Play `url` on the device's own media player as an announcement, queued behind one already playing; False
        when the device has no media player."""
        ...


class Connection(Link, Announcer, Protocol):
    async def connect(self, on_lost: Callable[[], Awaitable[None]]) -> None:
        """Connect and log in; `on_lost` is awaited once when the session ends after that. Raises
        aioesphomeapi.APIConnectionError (unreachable, wrong key, handshake) or OSError."""
        ...

    def subscribe_voice(self, on_start: OnStart, on_audio: OnAudio, on_stop: OnStop) -> None:
        """Ask the device to hand this session its wake-word runs, with the microphone's audio over the API."""
        ...

    async def disconnect(self) -> None: ...


class EsphomeConnection:
    """A `Connection` to `satellite.host`:6053 with Noise key `psk` (base64, as ESPHome's `api: encryption: key`)."""

    def __init__(self, satellite: Satellite, psk: str) -> None:
        self._client = APIClient(satellite.host, PORT, None, noise_psk=psk, client_info="ashley")
        self._player: int | None = None
        self._announcing = False

    async def connect(self, on_lost: Callable[[], Awaitable[None]]) -> None:
        async def stopped(_expected: bool) -> None:
            await on_lost()

        await self._client.connect(on_stop=stopped, login=True)
        entities, _ = await self._client.list_entities_services()
        self._player = next((e.key for e in entities if isinstance(e, MediaPlayerInfo)), None)
        if self._player is not None:
            self._client.subscribe_states(self._state)

    def _state(self, state: EntityState) -> None:
        if isinstance(state, MediaPlayerEntityState) and state.key == self._player:
            self._announcing = state.state == MediaPlayerState.ANNOUNCING

    def subscribe_voice(self, on_start: OnStart, on_audio: OnAudio, on_stop: OnStop) -> None:
        async def start(_conversation: str, _flags: int, _audio: VoiceAssistantAudioSettings,
                        _wake_word: str | None) -> int:
            await on_start()
            return 0   # 0: audio comes over the API connection, not a UDP port

        async def audio(data: bytes, _second_channel: bytes | None) -> None:
            await on_audio(data)

        self._client.subscribe_voice_assistant(handle_start=start, handle_stop=on_stop, handle_audio=audio)

    def send_event(self, event: VoiceAssistantEventType, data: dict[str, str] | None) -> None:
        self._client.send_voice_assistant_event(event, data)

    def announce(self, url: str) -> bool:
        # ESPHome's speaker media player starts an announcement sent without ENQUEUE at once, cutting off the one
        # playing, and starts an enqueued one only when the one playing ends, so ENQUEUE sent to an idle player waits.
        if self._player is None:
            return False
        self._client.media_player_command(self._player, media_url=url, announcement=True,
                                          command=MediaPlayerCommand.ENQUEUE if self._announcing else None)
        return True

    async def disconnect(self) -> None:
        await self._client.disconnect()
