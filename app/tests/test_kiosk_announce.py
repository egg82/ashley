"""The hallway's announcements on the screens someone is looking at (`ashley.channels.kiosk.announce`, through
`ashley.channels.voice.later.say`): a reply for the kiosk's `device:` thread goes to that kiosk when it is in the
foreground and someone is home (or it cannot be known), and to the foregrounded web page of each person known to be
away, as one clip of her voice with the reply's plain line; nothing goes when nobody is looking; a satellite's thread is
never a screen's; `voice.later` logs ids and counts, never the line or the token."""

from collections.abc import Generator
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.kiosk.announce import chosen
from ashley.channels.lexicon import Lexicon
from ashley.channels.lexicons import Lexicons, NullLexicons
from ashley.channels.model import Device, Listed
from ashley.channels.voice.clips import ClipsUnavailable
from ashley.channels.voice.later import say
from ashley.live.events import Announced, Shown
from ashley.live.live import Live
from ashley.live.screens import OpenScreen, Screens, ScreensUnavailable
from ashley.senses.presence import Presence
from contract.conversations_support import run
from house_devices_support import HouseDevices
from later_support import FakeClips, Logged, clips as clips, waiting
from live_support import FakeLive
from respond_support import FakePresence
from voice_support import FakeSpeaker, FakeTurnLoop, pipeline

HOUSEHOLD, KIOSK, SATELLITE = 1, 8, 3
ANN, BEA = 10, 11
MARK = "zqLEAK4471"


def kiosk(device_id: int = KIOSK) -> Listed:
    return Listed(Device(device_id, HOUSEHOLD, "tablet", "hallway", "present", "text", "command"), "other")


def satellite() -> Listed:
    return Listed(Device(SATELLITE, HOUSEHOLD, "echo", "office", "present", "spoken", "command"), "satellite")


def web(person: int, visible: bool | None = True) -> OpenScreen:
    return OpenScreen(person, None, visible)


def tablet(visible: bool | None = True, device_id: int = KIOSK) -> OpenScreen:
    return OpenScreen(None, device_id, visible)


@dataclass
class ListedScreens(Screens):
    """`open_screens` answers `screens`, or raises when `down`; nothing else is asked of it here."""

    screens: tuple[OpenScreen, ...] = ()
    down: bool = False
    asked: list[float] = field(default_factory=list[float])

    async def open_screens(self, household_id: int, within_s: float) -> tuple[OpenScreen, ...]:
        assert household_id == HOUSEHOLD
        self.asked.append(within_s)
        if self.down:
            raise ScreensUnavailable("down")
        return self.screens

    async def opened(self, household_id: int, person_id: int, token: str | None = None) -> int:
        raise AssertionError("not asked")

    async def device_opened(self, household_id: int, device_id: int, token: str | None = None) -> int:
        raise AssertionError("not asked")

    async def person_visible(self, person_id: int, token: str, visible: bool) -> None:
        raise AssertionError("not asked")

    async def device_visible(self, device_id: int, token: str, visible: bool) -> None:
        raise AssertionError("not asked")

    async def beat(self, screen_id: int) -> None:
        raise AssertionError("not asked")

    async def closed(self, screen_id: int) -> None:
        raise AssertionError("not asked")

    async def looking(self, person_id: int, within_s: float) -> bool:
        raise AssertionError("not asked")

    async def showing(self, device_id: int, within_s: float) -> bool:
        raise AssertionError("not asked")


class Respelled(NullLexicons):
    """Respells "Ashley" as "Ash Lee", so the clip's body can be told from its line."""

    async def of(self, household_id: int | None) -> Lexicon:
        return Lexicon({"Ashley": "Ash Lee"}) if household_id == HOUSEHOLD else await super().of(household_id)


@dataclass
class World:
    screens: ListedScreens
    presence: FakePresence
    live: FakeLive
    clips: FakeClips


@pytest.fixture
def world(clips: FakeClips) -> Generator[World]:
    made = World(ListedScreens(), FakePresence(), FakeLive(), clips)
    services.register(Screens, made.screens)
    services.register(Presence, made.presence)
    services.register(Live, made.live)
    services.register(Devices, HouseDevices({HOUSEHOLD: [kiosk(), satellite()]}))
    services.register(Lexicons, Respelled())
    yield made
    for kind in (Screens, Presence, Live, Devices, Lexicons):
        services.unregister(kind)


def announced(thread: str = f"device:{KIOSK}", body: str = "**Ashley** says someone is at the front door.") -> None:
    async def scenario() -> None:
        await say(waiting(thread, body, medium="text", age_ms=900), {}, pipeline(FakeTurnLoop(), FakeSpeaker()))

    run(scenario())


def sent(live: FakeLive) -> list[Shown]:
    assert all(isinstance(e, Announced) and e.clip == "tok-1" for e in live.published)
    return [e.shown for e in live.published]


@pytest.mark.parametrize(("screens", "home", "to"), [
    ((tablet(), web(ANN), web(BEA)), frozenset({ANN}), [Shown(HOUSEHOLD, None, KIOSK), Shown(HOUSEHOLD, BEA)]),
    ((tablet(), web(ANN)), frozenset({ANN, BEA}), [Shown(HOUSEHOLD, None, KIOSK)]),
    ((tablet(), web(ANN), web(BEA)), frozenset[int](), [Shown(HOUSEHOLD, ANN), Shown(HOUSEHOLD, BEA)]),
    ((tablet(), web(ANN)), None, [Shown(HOUSEHOLD, None, KIOSK)]),
    ((tablet(False), web(BEA, None), web(ANN, False)), frozenset({ANN}), []),
    ((tablet(device_id=KIOSK + 1), web(BEA, False), web(BEA)), frozenset({ANN}), [Shown(HOUSEHOLD, BEA)]),
])
def test_the_kiosk_when_someone_is_home_and_the_foregrounded_pages_of_those_away(
        screens: tuple[OpenScreen, ...], home: frozenset[int] | None, to: list[Shown]) -> None:
    assert list(chosen(HOUSEHOLD, KIOSK, screens, home)) == to


def test_a_reply_for_the_kiosk_is_one_clip_announced_to_each_chosen_screen(world: World,
                                                                           capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.screens.screens, world.presence.answer = (tablet(), web(ANN), web(BEA)), frozenset({ANN})
    announced()
    assert world.clips.added == [(KIOSK, "Ash Lee says someone is at the front door.", 900)]
    assert world.clips.lines == ["Ashley says someone is at the front door."]
    assert sent(world.live) == [Shown(HOUSEHOLD, None, KIOSK), Shown(HOUSEHOLD, BEA)]
    [line] = logged.events("voice.later")
    assert (line["device"], line["outcome"], line["clip"], line["screens"]) == (str(KIOSK), "screens", "1", "2")
    assert "front door" not in logged.text and "tok-1" not in logged.text


@pytest.mark.parametrize(("screens", "home", "outcome"), [
    ((tablet(False), web(ANN, None)), frozenset[int](), "no_screen"),
    ((tablet(), web(ANN)), frozenset({ANN}), "screens"),
    ((tablet(),), frozenset[int](), "no_screen"),
])
def test_nothing_is_stored_or_sent_when_nobody_chosen_is_looking(world: World, capsys: pytest.CaptureFixture[str],
                                                                 screens: tuple[OpenScreen, ...],
                                                                 home: frozenset[int] | None, outcome: str) -> None:
    logged = Logged(capsys)
    world.screens.screens, world.presence.answer = screens, home
    announced()
    [line] = logged.events("voice.later")
    assert line["outcome"] == outcome
    assert (len(world.clips.added), len(world.live.published)) == ((1, 1) if outcome == "screens" else (0, 0))


def test_screens_or_clips_down_send_nothing_and_say_why(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.screens.screens, world.presence.answer = (tablet(),), None
    world.screens.down = True
    announced()
    world.screens.down = False
    world.clips.error = ClipsUnavailable("down")
    announced()
    assert [e["outcome"] for e in logged.events("voice.later")] == ["screens_unavailable", "clips_unavailable"]
    assert world.live.published == []


def test_a_reply_with_no_words_is_not_announced(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.screens.screens = (tablet(),)
    announced(body="  ")
    assert [e["outcome"] for e in logged.events("voice.later")] == ["no_line"]
    assert world.screens.asked == [] and world.clips.added == []


def test_a_satellite_not_connected_and_an_unknown_device_are_never_a_screens(world: World,
                                                                            capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.screens.screens = (tablet(), web(ANN))
    announced(thread=f"device:{SATELLITE}", body=MARK)
    announced(thread="device:99", body=MARK)
    assert [e["outcome"] for e in logged.events("voice.later")] == ["not_connected", "not_connected"]
    assert world.screens.asked == [] and world.live.published == [] and MARK not in logged.text
