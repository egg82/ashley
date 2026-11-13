"""Saying one reply on a satellite, for the outbox's replies (`later`) and fired reminders (`reminders`): a clip,
played on the satellite's room speaker when it names one and Home Assistant accepts, else on the satellite's own media
player as an announcement."""

from ... import services
from ..model import Satellite
from .clips import Clips, ClipsUnavailable
from .connection import Announcer
from .run import Pipeline


async def said(body: str, age_ms: int, link: tuple[Satellite, Announcer] | None,
               pipeline: Pipeline) -> tuple[str, int | None]:
    """`body` said on the satellite `link` holds, `age_ms` after it was written: how (`room_speaker`, `announced`,
    `no_media_player`, `not_connected` when `link` is None, `clips_unavailable`) and the clip's id."""
    if link is None:
        return "not_connected", None
    satellite, session = link
    try:
        clip = await services.get(Clips).add(satellite.device.id, body, age_ms)
    except ClipsUnavailable:
        return "clips_unavailable", None
    url = f"{pipeline.clip_base_url}/api/voice/clips/{clip.token}"
    speaker, play = satellite.room_speaker, pipeline.play
    if speaker is not None and play is not None and await play(satellite.device.household_id, speaker, url):
        return "room_speaker", clip.id
    return ("announced" if session.announce(url) else "no_media_player"), clip.id
