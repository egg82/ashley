"""What waits on the signed-in person, what she keeps watching and what she did on her own, as `WorkItem`s, from
`ashley.channels.board`: their pending proposals, live watches, unasked actions and what she kept quiet."""

from ..channels import board
from .outside_models import ActionCause, ActionUndo
from .work_models import ActionUndone, KeptQuiet, KeptQuietEntry, WorkItem


def proposal_item(p: board.Pending) -> WorkItem:
    return WorkItem(kind="proposal", id=p.id, title=p.summary, state="waiting_on_you", lane="waiting", at=p.proposed_at,
                    conversation_id=p.conversation_id, can_tap=p.tap)


def watch_item(w: board.Kept) -> WorkItem:
    return WorkItem(kind="watch", id=w.id, title=w.label, state="paused" if w.held else "stopped" if w.paused else "running", lane="doing", at=w.at)


def action_item(d: board.Did) -> WorkItem:
    cause = None if d.cause is None else ActionCause(kind=d.cause.kind, id=d.cause.id)
    undo = None if d.undo is None else ActionUndo(kind=d.undo.kind, ref=d.undo.ref, within=d.undo.within)
    undone = None if d.undone is None else ActionUndone(at=d.undone.at, how=d.undone.how)
    return WorkItem(kind="action", id=d.id, title=d.summary, state="done", lane="on_her_own", at=d.at, cause=cause,
                    undo=undo, can_undo=undo is not None and undone is None, undone=undone)


def quiet_item(q: board.Quiet) -> WorkItem:
    """One summary item, never one per entry; its title is written here from the count."""
    latest = [KeptQuietEntry(why=e.why, at=e.at, cause=None if e.cause is None else ActionCause(kind=e.cause.kind, id=e.cause.id))
              for e in q.latest]
    title = "Kept quiet once" if q.count == 1 else f"Kept quiet {q.count} times"
    return WorkItem(kind="kept_quiet", id=q.id, title=title, state="done", lane="kept_quiet", at=q.latest[0].at,
                    kept_quiet=KeptQuiet(count=q.count, latest=latest))


async def pending_and_kept(household_id: int, person_id: int) -> list[WorkItem]:
    """Raises BoardUnavailable."""
    return ([proposal_item(p) for p in await board.pending(household_id, person_id)]
            + [watch_item(w) for w in await board.kept(household_id, person_id)]
            + [action_item(d) for d in await board.did(household_id, person_id)]
            + [quiet_item(q) for q in [await board.quiet(household_id, person_id)] if q is not None])
