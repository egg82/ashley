"""The satellite connections: one held session per satellite, reconnecting with doubling backoff and logging each
change once; a wake on the device becomes a run, a new wake abandons the old, an abort cancels it; the singleton body
follows `Devices.satellites` as it changes and closes everything when cancelled."""

import asyncio
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field

import pytest
from aioesphomeapi.core import APIConnectionError, InvalidEncryptionKeyAPIError
from aioesphomeapi.model import VoiceAssistantEventType as E
from ashley import logs, services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.model import Device, DiscordServer, Listed, Satellite
from ashley.channels.voice import config
from ashley.channels.voice.satellites import Satellites
from ashley.channels.voice.session import hold
from ashley.inference.inference import Inference
from contract.conversations_support import events
from voice_support import FRAME, FakeConnection, FakeSpeech, FakeTurnLoop, pipeline, settle

CONFIG = config.load()


def serving(connection: FakeConnection) -> Callable[[Satellite], Awaitable[FakeConnection]]:
    async def connect(_: Satellite) -> FakeConnection:
        return connection
    return connect
ECHO = Satellite(Device(5, 1, "office echo", "office", "present", "spoken", "command"), "10.0.0.9", None)


@pytest.fixture(autouse=True)
def speech() -> Generator[FakeSpeech]:
    fake = FakeSpeech(transcript="")
    services.register(Inference, fake)
    yield fake
    services.unregister(Inference)
    services.unregister(Devices)


class Sleeps:
    """A sleep that records what it was asked and yields once, so backoff costs no time."""

    def __init__(self) -> None:
        self.asked: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.asked.append(seconds)
        await asyncio.sleep(0)


def test_failed_connects_back_off_doubling_and_log_once_until_one_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    errors: list[Exception] = [OSError("unreachable"), InvalidEncryptionKeyAPIError("bad key"),
                               APIConnectionError("x"), TimeoutError()]
    connection = FakeConnection(failures=errors)
    sleeps = Sleeps()

    async def scenario() -> None:
        task = asyncio.create_task(hold(ECHO, serving(connection), pipeline(FakeTurnLoop()), CONFIG, sleeps))
        await settle()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    first = CONFIG.reconnect_first_s
    assert sleeps.asked == [first, first * 2, first * 4, first * 8]
    assert connection.connects == 5 and connection.disconnects == 1, "the held session is closed on cancel"
    out = capsys.readouterr().out
    assert [e["error"] for e in events(out, "voice.connect_failed")] == ["OSError"]
    assert [(e["device"], e["reconnect"]) for e in events(out, "voice.connected")] == [("5", "false")]


def test_a_lost_session_reconnects_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    sessions = [FakeConnection(), FakeConnection()]
    made: list[FakeConnection] = []

    async def connect(_: Satellite) -> FakeConnection:
        made.append(sessions[len(made)])
        return made[-1]

    async def scenario() -> None:
        task = asyncio.create_task(hold(ECHO, connect, pipeline(FakeTurnLoop()), CONFIG, Sleeps()))
        await settle()
        await sessions[0].lose()
        await settle()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(made) == 2 and sessions[0].disconnects == 0, "a session the device ended is not closed again"
    out = capsys.readouterr().out
    assert [e["reconnect"] for e in events(out, "voice.connected")] == ["false", "true"]
    assert len(events(out, "voice.disconnected")) == 1


def test_a_wake_on_the_device_is_a_run_and_a_second_wake_abandons_the_first(
        speech: FakeSpeech, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    connection = FakeConnection()

    async def scenario() -> None:
        task = asyncio.create_task(hold(ECHO, serving(connection), pipeline(FakeTurnLoop()), CONFIG, Sleeps()))
        await settle()
        assert connection.handlers is not None
        start, audio, stop = connection.handlers
        await start()
        await audio(FRAME)
        await settle()
        await start()                       # the device woke again before the first run ended
        for _ in range(3):
            await audio(FRAME)
        await stop(False)
        await settle()
        await start()
        await audio(FRAME)
        await stop(True)                    # aborted by the device
        await settle()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    outcomes = [e["outcome"] for e in events(capsys.readouterr().out, "voice.run")]
    assert outcomes == ["aborted", "empty", "aborted"]
    assert len(speech.heard) == 3, "the second run heard only its own audio"
    assert connection.kinds().count(E.VOICE_ASSISTANT_RUN_START) == 3


@dataclass
class ChangingDevices(Devices):
    answers: list[list[Satellite] | Exception] = field(default_factory=list[list[Satellite] | Exception])

    async def by_token(self, token: str) -> Device | None:
        return None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


def test_the_singleton_follows_the_satellites_as_they_change(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    moved = Satellite(ECHO.device, "10.0.0.10", None)
    other = Satellite(Device(6, 2, "kitchen echo", "kitchen", "present", "spoken", "command"), "10.0.0.11", None)
    services.register(Devices, ChangingDevices([[ECHO], DevicesUnavailable("x"), DevicesUnavailable("x"),
                                                [moved, other], []]))
    made: dict[str, list[FakeConnection]] = {}

    async def connect(satellite: Satellite) -> FakeConnection:
        made.setdefault(satellite.host, []).append(FakeConnection())
        return made[satellite.host][-1]

    polls = Sleeps()

    async def scenario() -> None:
        task = asyncio.create_task(Satellites(connect, pipeline(FakeTurnLoop()), CONFIG, polls).run())
        for _ in range(6):
            await settle()
        # checked while the singleton still runs: dropping a satellite closes it then, not only at shutdown
        assert set(made) == {"10.0.0.9", "10.0.0.10", "10.0.0.11"}
        assert made["10.0.0.9"][0].disconnects == 1, "a satellite whose host changed is let go"
        assert all(c.disconnects == 1 for c in (made["10.0.0.10"][0], made["10.0.0.11"][0])), "emptied, all closed"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert CONFIG.satellites_poll_s in polls.asked
    out = capsys.readouterr().out
    assert [e["count"] for e in events(out, "voice.satellites")] == ["1", "2", "0"]
    assert len(events(out, "voice.devices_unavailable")) == 1
