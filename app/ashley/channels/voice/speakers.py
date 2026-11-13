"""Replies the `Outbox` holds for a named speaker (`ashley.channels.wake.speaker`), said by the satellites singleton:
each taken reply becomes a clip and its URL is played on the speaker through Home Assistant, as a satellite's room
speaker is (`saying.said`). A reply that could not be played goes to the person's phone, queued as the push singleton
takes it, so a speaker that is off loses no wake's words.

Logs `voice.speaker_later` per reply taken: the speaker's person, outcome (`played` or `phone`, where it could not be
played), clip id (None for `phone`) and `age_ms`. Never text."""

import logging
from dataclasses import replace

from ... import logs, services
from ..devices import Devices, DevicesUnavailable
from ..outbox import Later, Outbox, OutboxUnavailable
from ..push.later import thread as phone_thread
from ..wake import speaker
from .clips import Clips, ClipsUnavailable
from .run import Pipeline

log = logging.getLogger("ashley.channels.voice")


async def say(later: Later, pipeline: Pipeline) -> None:
    named = speaker.parsed(later.thread)
    if named is None:
        return
    person, entity = named
    clip = await _clip(later, pipeline, entity)
    if clip is None:
        await _to_phone(later, person)
    logs.info(log, "voice.speaker_later", person=person, outcome="phone" if clip is None else "played", clip=clip,
              age_ms=later.age_ms)


async def _clip(later: Later, pipeline: Pipeline, entity: str) -> int | None:
    """The clip's id once it is playing on `entity`; None when it did not."""
    if pipeline.play is None:
        return None
    try:
        house = next((d for d in await services.get(Devices).of_household(later.household_id) if d.form == "house"),
                     None)
        if house is None:
            return None
        clip = await services.get(Clips).add(house.device.id, later.outbound.body, later.age_ms)
    except (DevicesUnavailable, ClipsUnavailable):
        return None
    url = f"{pipeline.clip_base_url}/api/voice/clips/{clip.token}"
    return clip.id if await pipeline.play(later.household_id, entity, url) else None


async def _to_phone(later: Later, person: int) -> None:
    try:
        await services.get(Outbox).add(later.household_id, phone_thread(person), replace(later.outbound, medium="text"))
    except OutboxUnavailable:
        logs.warning(log, "voice.speaker_later_lost", person=person)
