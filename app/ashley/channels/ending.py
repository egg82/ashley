"""One log line for every turn that ended after its first line went out without the answer it stood in for: `respond.ended`
with the conversation, the reason (`refused`, `inference_unavailable`, `outbox_unavailable`, `inflight_unavailable`,
`claim_lost`, `unstorable`, `gave_up`, `inference_rejected`) and the recovery taken: `told` (the fixed line for a
rejected request stood in as her answer, and the turn was not retried), `wrap_up` (another route wrapped the turn up),
`fixed_line` (the fixed line stood in), `kept` (the work was kept and another runner finishes it), `told_and_kept` (the
person was told she could not reach her thinking, and the work was kept), `failed_shown` (the work is gone and the
person's screens were told it failed), `other_runner` (another runner holds the turn). Ids only."""

import logging

from .. import logs

log = logging.getLogger("ashley.channels")


def record(reason: str, conversation_id: int | None, recovery: str) -> None:
    logs.info(log, "respond.ended", reason=reason, conversation=conversation_id, recovery=recovery)
