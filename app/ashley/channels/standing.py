"""What a turn's `Inbound` says about agreeing to held calls (`ashley.tools.outside`) and whose setting decides what it
may just do (`ashley.tools.trusting`), read from the fields the adapter set, never from what was said."""

from ..tools.outside import Standing
from ..tools.tools import Tools
from ..tools.trusting import Trusting
from .audience import owner_alone
from .model import Inbound


def of(inbound: Inbound) -> Standing | None:
    """The speaker's standing; None when the channel names no speaker. The reply is `private` when it reaches the speaker
    alone (`audience.owner_alone`); the turn is `agreeing` when it is a person's own message with no tainted origin, and
    `unasked` when no person's message started it (`Inbound.unprompted`), with the record that did as its `cause`."""
    if inbound.speaker_id is None:
        return None
    return Standing(inbound.household_id, inbound.speaker_id, owner_alone(inbound),
                    inbound.author == "person" and inbound.taint is None, inbound.unprompted,
                    inbound.cause if inbound.unprompted else None)


def trusting(inbound: Inbound, source: Tools) -> Tools:
    """`source` behind the setting of the person the turn is for (`tools.trusting.Trusting`) on a turn no person's message
    started (`Inbound.unprompted`) that names them; as it is on any other. A person's own message is their yes, so what
    they ask for in it is not offered back to them."""
    if not inbound.unprompted or inbound.speaker_id is None:
        return source
    return Trusting(source, inbound.household_id, inbound.speaker_id)
