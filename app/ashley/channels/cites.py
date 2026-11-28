"""Her reply's `cites` checked against the records her calls returned this turn (`ToolResult.citable`), as a bench
checks a cited turn against the talk (`workshop.facts.cited_turns`): a number no call returned is dropped, never read
from her words. Logs `reply.cites` with how many she cited, kept, and dropped as unreturned or as having no card."""

import logging
from collections.abc import Mapping, Sequence

from .. import logs
from ..conversations.model import Shown

log = logging.getLogger("ashley.channels")


def checked(cites: Sequence[int], citable: Mapping[int, Shown | None], conversation_id: int) -> tuple[Shown, ...]:
    """What each number of `cites` names in `citable`, each once in the order cited; a number missing from `citable`, or
    naming a record no card draws (None), is left out."""
    if not cites:
        return ()
    named = tuple(dict.fromkeys(cites))
    returned = [citable[n] for n in named if n in citable]
    kept = tuple(s for s in returned if s is not None)
    logs.info(log, "reply.cites", conversation=conversation_id, cited=len(named), kept=len(kept),
              unreturned=len(named) - len(returned), uncarded=len(returned) - len(kept))
    return kept
