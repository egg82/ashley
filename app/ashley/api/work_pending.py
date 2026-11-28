"""What waits on the signed-in person and what she keeps watching, as `WorkItem`s, from `ashley.channels.board`: their
pending proposals and live watches."""

from ..channels import board
from .work_models import WorkItem


def proposal_item(p: board.Pending) -> WorkItem:
    return WorkItem(kind="proposal", id=p.id, title=p.summary, state="waiting_on_you", lane="waiting", at=p.proposed_at,
                    conversation_id=p.conversation_id, can_tap=p.tap)


def watch_item(w: board.Kept) -> WorkItem:
    return WorkItem(kind="watch", id=w.id, title=w.label, state="stopped" if w.paused else "running", lane="doing", at=w.at)


async def pending_and_kept(household_id: int, person_id: int) -> list[WorkItem]:
    """Raises BoardUnavailable."""
    return ([proposal_item(p) for p in await board.pending(household_id, person_id)]
            + [watch_item(w) for w in await board.kept(household_id, person_id)])
