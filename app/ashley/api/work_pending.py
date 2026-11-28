"""What waits on the signed-in person, what she keeps watching and what she did on her own, as `WorkItem`s, from
`ashley.channels.board`: their pending proposals, live watches and unasked actions."""

from ..channels import board
from .outside_models import ActionCause, ActionUndo
from .work_models import WorkItem


def proposal_item(p: board.Pending) -> WorkItem:
    return WorkItem(kind="proposal", id=p.id, title=p.summary, state="waiting_on_you", lane="waiting", at=p.proposed_at,
                    conversation_id=p.conversation_id, can_tap=p.tap)


def watch_item(w: board.Kept) -> WorkItem:
    return WorkItem(kind="watch", id=w.id, title=w.label, state="stopped" if w.paused else "running", lane="doing", at=w.at)


def action_item(d: board.Did) -> WorkItem:
    cause = None if d.cause is None else ActionCause(kind=d.cause.kind, id=d.cause.id)
    undo = None if d.undo is None else ActionUndo(kind=d.undo.kind, ref=d.undo.ref, within=d.undo.within)
    return WorkItem(kind="action", id=d.id, title=d.summary, state="done", lane="on_her_own", at=d.at, cause=cause,
                    undo=undo)


async def pending_and_kept(household_id: int, person_id: int) -> list[WorkItem]:
    """Raises BoardUnavailable."""
    return ([proposal_item(p) for p in await board.pending(household_id, person_id)]
            + [watch_item(w) for w in await board.kept(household_id, person_id)]
            + [action_item(d) for d in await board.did(household_id, person_id)])
