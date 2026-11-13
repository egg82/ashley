"""The Home Assistant media player a wake rule names (`WakeRule.speaker`), where the wake's turn is said aloud instead
of pushed to the phone. The turn runs on the thread `device:speaker:<person id>:<entity id>`, which the satellites
singleton drains (`ashley.channels.voice.speakers`) and plays as it does a room's reply: a clip fetched from the clips
route.

The entity is checked against the household's own house when the wake runs: only an entity the house lists is used;
any other (renamed, removed, no house) leaves the turn on the phone, logged `wakes.speaker` with the outcome
`unknown`."""

import logging
from dataclasses import replace

from ... import logs
from ...senses.house_lists import lists
from ..model import Inbound

PREFIX = "device:speaker:"

log = logging.getLogger("ashley.channels.wake")


def thread(person_id: int, entity_id: str) -> str:
    return f"{PREFIX}{person_id}:{entity_id}"


def parsed(name: str) -> tuple[int, str] | None:
    """The person id and entity id a thread `device:speaker:<person id>:<entity id>` names; None for any other."""
    person, _, entity = name.removeprefix(PREFIX).partition(":")
    return (int(person), entity) if name.startswith(PREFIX) and person.isdigit() and entity else None


async def listed(wake_id: int, household_id: int, entity_id: str) -> bool:
    """Whether the household's house lists `entity_id`, which a rule's speaker is already shaped as a media player of.
    Raises HouseUnreadable."""
    found = await lists(household_id, entity_id)
    logs.info(log, "wakes.speaker", wake=wake_id, household=household_id, outcome="named" if found else "unknown")
    return found


def moved(phone: Inbound, person_id: int, entity_id: str) -> Inbound:
    """`phone` as the turn said on the speaker: spoken, for whoever is in earshot."""
    return replace(phone, thread=thread(person_id, entity_id), medium="spoken", audience="present", shared=True)
