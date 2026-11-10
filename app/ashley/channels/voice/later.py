"""Replies the `Outbox` holds for satellites, said by the satellites singleton: each taken reply for a thread
`device:<id>` becomes a clip, played on the satellite's room speaker when it names one and Home Assistant accepts, else
on the satellite's own media player as an announcement. A reply for a satellite not connected now is dropped.

Logs `voice.later` per reply taken: device (None when the thread names no satellite), outcome (`room_speaker`,
`announced`, `no_media_player`, `not_connected`, `clips_unavailable`), clip id and `age_ms`, how long it waited; and
`voice.outbox_unavailable` once per run of failed takes. Never text."""

import logging

from ... import logs, services
from ..model import Satellite
from ..outbox import Later, Outbox, OutboxUnavailable
from .clips import Clips, ClipsUnavailable
from .connection import Announcer
from .run import Pipeline
from .session import Links, Sleep

log = logging.getLogger("ashley.channels.voice")

PREFIX = "device:"


async def drain(links: Links, pipeline: Pipeline, poll_s: float, sleep: Sleep) -> None:
    """Every `poll_s` until cancelled, say each reply waiting for a satellite; `links` maps each connected
    satellite's device id to it and its session."""
    failing = False
    while True:
        try:
            waiting = await services.get(Outbox).take(PREFIX)
        except OutboxUnavailable:
            if not failing:
                logs.warning(log, "voice.outbox_unavailable")
            failing = True
        else:
            failing = False
            for later in waiting:
                await say(later, links, pipeline)
        await sleep(poll_s)


async def say(later: Later, links: Links, pipeline: Pipeline) -> None:
    device = _device(later.thread)
    outcome, clip = await _said(later, links.get(device) if device is not None else None, pipeline)
    logs.info(log, "voice.later", device=device, outcome=outcome, clip=clip, age_ms=later.age_ms)


async def _said(later: Later, link: tuple[Satellite, Announcer] | None, pipeline: Pipeline) -> tuple[str, int | None]:
    if link is None:
        return "not_connected", None
    satellite, session = link
    try:
        clip = await services.get(Clips).add(satellite.device.id, later.outbound.body, later.age_ms)
    except ClipsUnavailable:
        return "clips_unavailable", None
    url = f"{pipeline.clip_base_url}/api/voice/clips/{clip.token}"
    speaker, play = satellite.room_speaker, pipeline.play
    if speaker is not None and play is not None and await play(satellite.device.household_id, speaker, url):
        return "room_speaker", clip.id
    return ("announced" if session.announce(url) else "no_media_player"), clip.id


def _device(thread: str) -> int | None:
    """The satellite a thread `device:<id>` names; None for any other thread, such as a device's named thread."""
    rest = thread.removeprefix(PREFIX)
    return int(rest) if rest != thread and rest.isdigit() else None
