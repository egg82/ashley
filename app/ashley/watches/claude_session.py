"""The `claude_session` kind: a person's Claude Code sessions on their herdr bridge. One `Bridge.sessions` call serves
every watch of the person; a watch keeps only its target, an item keyed by session id with the kind's tracked
fields. A target the bridge no longer lists reads as no items, which is gone."""

from collections.abc import Mapping, Sequence

from .. import services
from ..criteria.record import Change
from ..connections import ports
from ..connections.connections import Connections
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed, Reason, Session
from .config import CONFIG
from .diff import Items, to_items
from .kinds import Kind
from .model import FailReason, Read, ReadFailed, Watch

NAME = "claude_session"
DONE_NOTE = ("A Claude Code session has stopped and is waiting for input. That is not always the "
             "end of its work: it also stops while its own subagents or background commands are still running, and "
             "goes on when they report. The message names it; none of what is on its screen is in it. Read the end of "
             "it with claude_read. If it is still waiting on work of its own, nothing has finished: set worth_saying "
             "false, and you are woken again when it next stops. Otherwise decide what to do: tell the person what it "
             "did and where the result is, or act with your tools. With worth_saying false nothing is posted or "
             "pushed to anyone, and what you did with your tools stands. If you cannot read it, say that it stopped, "
             "not that it finished, or stay silent.")
BLOCKED_NOTE = ("A Claude Code session is blocked on a dialog only the person can answer, and you "
                "cannot answer it. Read the end of its screen with claude_read to see what it asks, then decide whether "
                "to tell them what it is waiting for so they can answer it where it runs. With worth_saying false "
                "nothing is posted or pushed to anyone.")
CLOSED_NOTE = ("A Claude Code session you watch has closed. Say so if the person would want to know; with "
                "worth_saying false nothing is posted or pushed to anyone.")
_REASONS: dict[Reason, FailReason] = {"herdr_unavailable": "unreachable", "unconfirmed": "unreachable",
                                      "bad_token": "refused", "wrong_person": "refused", "pin_mismatch": "refused"}


class ClaudeSession(Kind):
    name = NAME

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        first = group[0]
        listed = await _listed(first.household_id, first.person_id)
        if isinstance(listed, ReadFailed):
            return _all(group, listed)
        return {w.id: items_of(w.target, listed.get(w.target)) for w in group}

    def said(self, watch: Watch, changes: Sequence[Change]) -> str:
        return f"Claude Code session {watch.label}: {_status(changes)}"

    def note(self, watch: Watch, changes: Sequence[Change]) -> str:
        status = _status(changes)
        return CLOSED_NOTE if status == "closed" else BLOCKED_NOTE if status == "blocked" else DONE_NOTE

    async def available(self, household_id: int, person_id: int) -> bool:
        return await ports.opened(services.get(Connections), "herdr", household_id, person_id) is not None

    async def label(self, watch: Watch) -> str:
        listed = await _listed(watch.household_id, watch.person_id)
        session = None if isinstance(listed, ReadFailed) else listed.get(watch.target)
        return watch.target if session is None else session.label


async def _listed(household_id: int, person_id: int) -> dict[str, Session] | ReadFailed:
    """The person's sessions by id, or why the bridge could not say."""
    opened = await ports.opened(services.get(Connections), "herdr", household_id, person_id)
    if opened is None:
        return ReadFailed("not_connected")
    try:
        access = Access.of(opened.connection.base_url, opened.secret, person_id)
        found = await services.get(Bridge).sessions(access)
    except BridgeFailed as e:
        return ReadFailed(_REASONS.get(e.reason, "bad_result"))
    return {s.id: s for s in found.sessions}


def _all(group: Sequence[Watch], failed: ReadFailed) -> Mapping[int, Read]:
    return {w.id: failed for w in group}


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
