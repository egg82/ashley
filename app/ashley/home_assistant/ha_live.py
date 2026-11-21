"""Home Assistant's camera WebRTC commands as the House port's live feed (`ha_house.HaHouse`): the client configuration
(`camera/webrtc/get_client_config`), the offer, whose subscription then streams the session, the answer and the camera's
candidates (`camera/webrtc/offer`), and the browser's candidates (`camera/webrtc/candidate`). Home Assistant ends a session
when the offer's connection closes, so the offer's connection is held open for the feed. Message shapes are Home Assistant's
own: `homeassistant/components/camera/webrtc.py` in core and `src/data/camera.ts` in its frontend."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from ..cameras.model import Candidate, IceServer, LiveAnswer, LiveCandidate, LiveConfig, LiveRefused, LiveSession, LiveSignal
from .ha_json import names, obj, rows, text
from .ha_socket import Commands


def config_of(result: object) -> LiveConfig:
    """The `get_client_config` result: `configuration.iceServers`, each with `urls` (a string or a list), `username` and
    `credential`, and an optional `dataChannel`."""
    got = obj(result)
    servers = tuple(IceServer(_urls(s.get("urls")), text(s.get("username")) or None, text(s.get("credential")) or None)
                    for s in rows(obj(got.get("configuration")).get("iceServers")))
    return LiveConfig(tuple(s for s in servers if s.urls), text(got.get("dataChannel")) or None)


def _urls(value: object) -> tuple[str, ...]:
    """An ICE server's `urls`: one string or a list of them."""
    return (value,) if isinstance(value, str) and value else names(value)


def candidate_of(raw: object) -> Candidate | None:
    """A candidate as Home Assistant sends it (an `RTCIceCandidateInit`); None when it names no candidate."""
    got = obj(raw)
    line = text(got.get("candidate"))
    index = got.get("sdpMLineIndex")
    if not line:
        return None
    return Candidate(line, text(got.get("sdpMid")) or None, index if isinstance(index, int) and not isinstance(index, bool)
                     else None, text(got.get("usernameFragment")) or None)


def signal_of(event: object) -> LiveSignal | None:
    """One event of the offer's subscription as a signal; None for a type this does not read."""
    got = obj(event)
    kind = got.get("type")
    if kind == "session" and text(got.get("session_id")):
        return LiveSession(text(got["session_id"]))
    if kind == "answer" and text(got.get("answer")):
        return LiveAnswer(text(got["answer"]))
    if kind == "candidate":
        found = candidate_of(got.get("candidate"))
        return None if found is None else LiveCandidate(found)
    if kind == "error":
        return LiveRefused(text(got.get("code")) or "error")
    return None


def candidate_json(candidate: Candidate) -> dict[str, object]:
    """`candidate` as the `RTCIceCandidateInit` Home Assistant takes."""
    shown: dict[str, object] = {"candidate": candidate.candidate, "sdpMid": candidate.sdp_mid,
                                "sdpMLineIndex": candidate.sdp_m_line_index}
    if candidate.username_fragment is not None:
        shown["usernameFragment"] = candidate.username_fragment
    return shown


class HaLive:
    def __init__(self, commands: Commands) -> None:
        self._commands = commands

    async def config(self, camera: str) -> LiveConfig:
        return config_of(await self._commands.run({"type": "camera/webrtc/get_client_config", "entity_id": camera}))

    def feed(self, camera: str, offer: str) -> AbstractAsyncContextManager[AsyncIterator[LiveSignal]]:
        return self._feed(camera, offer)

    @asynccontextmanager
    async def _feed(self, camera: str, offer: str) -> AsyncGenerator[AsyncIterator[LiveSignal]]:
        async with self._commands.subscribe({"type": "camera/webrtc/offer", "entity_id": camera, "offer": offer}) as events:
            yield _signals(events)

    async def candidate(self, camera: str, session_id: str, candidate: Candidate) -> None:
        await self._commands.run({"type": "camera/webrtc/candidate", "entity_id": camera, "session_id": session_id,
                                  "candidate": candidate_json(candidate)})


async def _signals(events: AsyncIterator[object]) -> AsyncIterator[LiveSignal]:
    async for event in events:
        signal = signal_of(event)
        if signal is not None:
            yield signal
