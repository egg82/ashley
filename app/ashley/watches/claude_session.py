"""The `claude_session` kind: a person's Claude Code sessions on their herdr bridges, one per machine. One
`Bridge.sessions` call per machine serves every watch of the person; a watch keeps only its target, an item keyed by
session id (unique across machines) with the kind's tracked fields. A target no machine lists reads as no items, which
is gone, unless a machine did not answer: the session may be on it, so the watch reads as failed instead."""

from collections.abc import Mapping, Sequence

from .. import services
from ..criteria.record import Change
from ..herdr import machines
from ..herdr.bridge import Bridge
from ..herdr.model import BridgeFailed, Reason, Session
from .config import CONFIG
from .diff import Items, to_items
from .kinds import Kind
from .model import FailReason, Read, ReadFailed, Watch

NAME = "claude_session"
DONE_NOTE = ("A Claude Code session has stopped and is waiting for input. That is not always the "
             "end of its work: it also stops while its own subagents or background commands are still running, and "
             "goes on when they report. The message names it; none of what is on its screen is in it. Read the end of "
             "it with claude_read. If it is still waiting on work of its own, nothing has finished: set `says` "
             "to none, and you are woken again when it next stops. Otherwise decide what to do: tell the person what it "
             "did and where the result is, or act with your tools. With `says` none nothing is posted or "
             "pushed to anyone, and what you did with your tools stands. If you cannot read it, say that it stopped, "
             "not that it finished, or stay silent.")
BLOCKED_NOTE = ("A Claude Code session is blocked on a dialog only the person can answer, and you "
                "cannot answer it. Read the end of its screen with claude_read to see what it asks, then decide whether "
                "to tell them what it is waiting for so they can answer it where it runs. With `says` none "
                "nothing is posted or pushed to anyone.")
CLOSED_NOTE = ("A Claude Code session you watch has closed. Say so if the person would want to know; with "
                "`says` none nothing is posted or pushed to anyone.")
_REASONS: dict[Reason, FailReason] = {"herdr_unavailable": "unreachable", "unconfirmed": "unreachable",
                                      "bad_token": "refused", "wrong_person": "refused", "pin_mismatch": "refused"}


class ClaudeSession(Kind):
    name = NAME

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        first = group[0]
        listed, failed = await _listed(first.household_id, first.person_id)
        return {w.id: items_of(w.target, listed[w.target]) if w.target in listed else failed or {} for w in group}

    def said(self, watch: Watch, changes: Sequence[Change]) -> str:
        return f"Claude Code session {watch.label}: {_status(changes)}"

    def note(self, watch: Watch, changes: Sequence[Change]) -> str:
        status = _status(changes)
        return CLOSED_NOTE if status == "closed" else BLOCKED_NOTE if status == "blocked" else DONE_NOTE

    async def available(self, household_id: int, person_id: int) -> bool:
        return bool(await machines.held(household_id, person_id))

    async def label(self, watch: Watch) -> str:
        listed, _ = await _listed(watch.household_id, watch.person_id)
        session = listed.get(watch.target)
        return watch.target if session is None else session.label


async def _listed(household_id: int, person_id: int) -> tuple[dict[str, Session], ReadFailed | None]:
    """The sessions by id of the machines that answered, and why the first that did not could not say (`not_connected`
    when the person holds no machine)."""
    held = await machines.held(household_id, person_id)
    if not held:
        return {}, ReadFailed("not_connected")
    found: dict[str, Session] = {}
    failed: ReadFailed | None = None
    for machine in held:
        try:
            found |= {s.id: s for s in (await services.get(Bridge).sessions(machine.access)).sessions}
        except BridgeFailed as e:
            failed = failed or ReadFailed(_REASONS.get(e.reason, "bad_result"))
    return found, failed


def _status(changes: Sequence[Change]) -> str:
    """The session's status after the last change, `closed` when it is gone."""
    if not changes:
        return "unknown"
    after = changes[-1].after
    return "closed" if after is None else str(after.get("status"))


def items_of(target: str, session: Session | None) -> Items:
    """What the session reads as for a watch on `target`: its tracked fields, or no items when it is not listed."""
    if session is None:
        return {}
    values = {"status": session.status, "seq": session.seq}
    return to_items({target: {f: values[f] for f in CONFIG.kinds[NAME].track}}, CONFIG.max_value_chars)
