"""A camera's live feed on the screens someone is looking at. Which screens show one is the open-screens record
(`ashley.live.screens.Screens.show_feed`), so either site can show it, read it back and clear it, and a screen that opens
later shows nothing it was not shown. She puts it on (`show`) where `ashley.channels.kiosk.announce.chosen` says a reply
would be heard: the kiosk when its page is in the foreground and someone is home, and the foregrounded web page of each
person known to be away. It leaves on its own after `feed_s` (`ashley.live.live`), when a person swipes it away
(`dismiss`) or when she takes it down (`clear`). A screen reads its own feed back (`current`) and relays its offer for it
(`relay`, `candidate`) under the token it opened its live feed with, so a page can only open the feed it is shown.
Live carries only "something changed" (`ashley.live.events.FeedChanged`)."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from ... import services
from ...live.events import FeedChanged, Shown
from ...live.live import Live, load as live_config
from ...live.screens import Screens
from ...senses.presence import Presence
from ...tools import camera_feed
from ...tools.camera_feed import FeedRefused as FeedRefused
from ..devices import Devices
from .announce import PRESENT_S, chosen

FEED_S = live_config().feed_s


class NotShowing(Exception):
    """The screen that asked shows no feed now (it never did, its time is up, or it was taken off)."""


@dataclass(frozen=True)
class Owner:
    """The owner of one open screen, as `ashley.live.screens.Screens` names it: a person's page or a paired device,
    exactly one of them."""

    household_id: int
    person_id: int | None
    device_id: int | None


@dataclass(frozen=True)
class Showing:
    """What a screen shows: the camera's `camera_id` and `title`, the `remaining_s` it stays, and what its browser needs
    to open it (`config`, as `ashley.tools.camera_feed.config`, empty when that could not be read)."""

    camera_id: str
    title: str
    remaining_s: float
    config: dict[str, object]


async def screens_in_reach(household_id: int, person_id: int | None, device_id: int | None) -> tuple[int, ...]:
    """The screen devices a turn may use: the device whose own thread it is, else every screen of the household for a known
    speaker. Raises DevicesUnavailable."""
    screens = await screens_of(household_id)
    if device_id is not None:
        return (device_id,) if device_id in screens else ()
    return screens if person_id is not None else ()


async def screens_of(household_id: int) -> tuple[int, ...]:
    """The household's screen devices (the kiosks), by id. Raises DevicesUnavailable."""
    return tuple(sorted({d.device.id for d in await services.get(Devices).of_household(household_id) if d.form == "other"}))


async def show(household_id: int, camera_id: str, reach: tuple[int, ...], now: datetime) -> int:
    """Put the feed of `camera_id` on the screens `chosen` picks for each device in `reach`; how many screens it went to.
    Announces the change on Live when any did. Raises ScreensUnavailable, DevicesUnavailable."""
    found = await services.get(Screens).open_screens(household_id, PRESENT_S)
    home = await services.get(Presence).home(household_id)
    picked = [s for device in reach for s in chosen(household_id, device, found, home)]
    people = tuple(sorted({s.person_id for s in picked if s.person_id is not None}))
    devices = tuple(sorted({s.device_id for s in picked if s.device_id is not None}))
    count = await services.get(Screens).show_feed(household_id, camera_id, now + timedelta(seconds=FEED_S), people, devices,
                                                  PRESENT_S)
    if count:
        services.get(Live).publish(FeedChanged(Shown(household_id, None)))
    return count


async def clear(household_id: int) -> int:
    """Take the feed off every screen of the household; how many showed one. Raises ScreensUnavailable."""
    count = await services.get(Screens).clear_feed(household_id)
    if count:
        services.get(Live).publish(FeedChanged(Shown(household_id, None)))
    return count


async def current(owner: Owner, token: str, now: datetime) -> Showing:
    """The feed the screen under `token` shows, when its camera is still one she may show. Raises NotShowing,
    ScreensUnavailable, `camera_feed.FeedRefused` (`unavailable`: the camera's list cannot be read now)."""
    feed = await services.get(Screens).feed_of(token, now, owner.person_id, owner.device_id)
    if feed is None:
        raise NotShowing
    try:
        title = await camera_feed.titled(owner.household_id, feed.camera_id)
    except camera_feed.FeedRefused as e:
        if e.reason == "no_such_camera":
            raise NotShowing from None
        raise
    try:
        config = await camera_feed.config(owner.household_id, feed.camera_id)
    except camera_feed.FeedRefused:
        config = {}
    return Showing(feed.camera_id, title, (feed.until - now).total_seconds(), config)


async def check(owner: Owner, token: str, now: datetime) -> None:
    """Whether the screen under `token` shows a feed of a camera she may still show. Raises NotShowing,
    ScreensUnavailable, `camera_feed.FeedRefused`."""
    feed = await services.get(Screens).feed_of(token, now, owner.person_id, owner.device_id)
    if feed is None:
        raise NotShowing
    await camera_feed.titled(owner.household_id, feed.camera_id)


async def dismiss(owner: Owner, token: str) -> None:
    """Take the feed off the screen under `token`. Raises ScreensUnavailable."""
    await services.get(Screens).dismiss_feed(token, owner.person_id, owner.device_id)


def relay(owner: Owner, token: str, offer: str, now: datetime) -> AbstractAsyncContextManager[
        tuple[float, AsyncIterator[dict[str, object]]]]:
    """Pass the offer of the screen under `token` to the camera it shows and yield the seconds that feed has left and what
    comes back (`ashley.tools.camera_feed.relay`). Raises NotShowing, ScreensUnavailable, `camera_feed.FeedRefused` (the
    camera is no longer one she may show) on entering."""
    return _relay(owner, token, offer, now)


@asynccontextmanager
async def _relay(owner: Owner, token: str, offer: str,
                 now: datetime) -> AsyncGenerator[tuple[float, AsyncIterator[dict[str, object]]]]:
    feed = await services.get(Screens).feed_of(token, now, owner.person_id, owner.device_id)
    if feed is None:
        raise NotShowing
    async with camera_feed.relay(owner.household_id, feed.camera_id, offer) as signals:
        yield (feed.until - now).total_seconds(), signals


async def candidate(owner: Owner, token: str, now: datetime, session_id: str, line: str, sdp_mid: str | None,
                    sdp_m_line_index: int | None, username_fragment: str | None) -> None:
    """Hand the browser's candidate to the camera the screen under `token` shows. Raises NotShowing, ScreensUnavailable,
    `camera_feed.FeedRefused`."""
    feed = await services.get(Screens).feed_of(token, now, owner.person_id, owner.device_id)
    if feed is None:
        raise NotShowing
    await camera_feed.candidate(owner.household_id, feed.camera_id, session_id, line, sdp_mid, sdp_m_line_index,
                                username_fragment)


