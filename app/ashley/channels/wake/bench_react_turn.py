"""The turn a quiet bench starts: an `Inbound` nobody is waiting on (`unprompted`) on the bench's own thread, as the
bench's owner is the one it is with, so her bench tools, memory and the hearing rule are theirs. The owner is on the
bench's page by construction, so the turn is `watched` and holds as a person's does. The stored message is
the household's turn, written from ids and kinds alone (`said`), never a piece's words; what she is told to do reaches
her only as the turn's `note`. Its `source` is the bench and the last command handed, so a reaction handed in twice is
one turn."""

from datetime import tzinfo

from ...stamp import stamp
from ...workshop.reactions import Done, Unseen
from ..model import Inbound


def source_of(unseen: Unseen) -> str:
    return f"bench_react:{unseen.bench_id}:{unseen.to_seq}"


def inbound(unseen: Unseen, zone: tzinfo) -> Inbound:
    return Inbound(household_id=unseen.household_id, thread=f"bench:{unseen.bench_id}", text=said(unseen, zone),
                   kind="brainstorm", medium="text", audience="owner", speaker_id=unseen.owner_id, shared=False,
                   place=None, channel="web", later=True, later_by="turn", bench_id=unseen.bench_id, on_page=True,
                   source=source_of(unseen), unprompted=True, author="household", note=NOTE, watched=True, taint=None)


def said(unseen: Unseen, zone: tzinfo) -> str:
    """What the person did, by command number, kind of change and piece, each with when it was, in `zone`."""
    listed = ", ".join(_one(d, zone) for d in unseen.done)
    more = unseen.count - len(unseen.done)
    return f"{unseen.count} changes on the bench: {listed}" + (f" (and {more} earlier)" if more > 0 else "")


def _one(done: Done, zone: tzinfo) -> str:
    piece = "" if done.piece_id is None else f" {done.kind or 'piece'} {done.piece_id}"
    return f"#{done.seq} {done.type}{piece} ({stamp(done.at, zone)})"


NOTE = ("The person has stopped changing the bench for a moment. The message lists what they did by command number, "
        "kind of change and piece, with none of their words; read a piece with your bench tools if you need what it "
        "says. Set worth_saying true only if you have something worth telling them now. If not, set it false and "
        "nothing is posted. While you work, the person sees your aside line to them, so make it say what you are "
        "doing.")
