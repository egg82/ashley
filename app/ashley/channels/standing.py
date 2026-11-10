"""What a turn's `Inbound` says about agreeing to held calls (`ashley.tools.outside`), read from the fields the adapter
set, never from what was said."""

from ..tools.outside import Standing
from .audience import owner_alone
from .model import Inbound


def of(inbound: Inbound) -> Standing | None:
    """The speaker's standing; None when the channel names no speaker. The reply is `private` when it reaches the speaker
    alone (`audience.owner_alone`); the turn is `agreeing` when it is a person's own message with no tainted origin."""
    if inbound.speaker_id is None:
        return None
    return Standing(inbound.household_id, inbound.speaker_id, owner_alone(inbound),
                    inbound.author == "person" and inbound.taint is None)
