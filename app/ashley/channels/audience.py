"""Whether a reply reaches the speaker alone, which decides what may be offered on a turn that acts with a person's or
their household's authority (the money tools). Read from the fields the adapter set, never from what was said."""

from ..connections.resources import Use
from .model import Inbound


def owner_alone(inbound: Inbound) -> bool:
    """True only when the channel itself names the speaker (`speaker_id`, never a voice match) and only they read or
    hear the reply: audience `owner`, not a shared channel, and no device's screen showing the thread. A person's web
    chat, their bench's talk and their Discord DM are; a satellite, the hallway tablet and a household's Discord
    channel are not."""
    return (inbound.speaker_id is not None and inbound.audience == "owner" and not inbound.shared
            and inbound.device_id is None)


def use_of(inbound: Inbound) -> Use:
    """What the resource gate (`ConnectionResources.usable`) needs of a turn: its household, the speaker the channel
    names, and whether the reply reaches that speaker alone."""
    return Use(inbound.household_id, inbound.speaker_id, owner_alone(inbound))
