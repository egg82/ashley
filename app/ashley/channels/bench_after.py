"""What a turn on a bench sets going once her reply is stored: the tidy pass over the bench's text pieces
(`ashley.tidy.run`), apart from the reply, which never waits on it. A turn that is not a known person's on a bench sets
nothing going; whether the pass asks anything of a model is its own judgement of what changed."""

from ..people.model import Person
from ..tidy import run
from ..workshop.model import Owner
from .model import Inbound


def tidy(inbound: Inbound, speaker: Person | None) -> None:
    """The pass for the bench the turn ended on (the one its page was moved to, else its own), for the speaker who owns it."""
    bench = inbound.bench_id if inbound.moved_to is None else inbound.moved_to
    if bench is not None and speaker is not None:
        run.start(Owner(inbound.household_id, speaker.id), bench)
