"""Who a turn behind `tools.outside.Outside` answers (`Standing`), and the one place a change she made with no one's OK
is written to the `OutsideRecord`: a change a tainted turn's tier or judge let run, and any change of a turn no person's
message started (`decisions.md`, "What she did on her own is one record"). Logs `outside.recorded` with ids, the tool,
the tier and the kinds of its cause and undo, and `outside.unrecorded`; never a summary or an explanation."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import logs, services
from ..inference.model import Tier, ToolCall, ToolResult, ToolSpec
from ..receipts import Receipt
from ..senses.outside_record import Cause, DoneAction, OutsideRecord, OutsideRecordUnavailable
from . import outside_summary
from .action_judge import Verdict
from .outside_config import OutsideConfig

log = logging.getLogger("ashley.tools")


@dataclass(frozen=True)
class Standing:
    """Who the turn answers, from the channel's fields: the `speaker_id` of `household_id`, whether the reply reaches them
    alone (`private`, `channels.audience.owner_alone`), whether the turn may agree to held calls (`agreeing`: a
    person's own message whose origin is not tainted), and whether no person's message started it (`unasked`), with
    the record that did (`cause`, None when its builder names none)."""

    household_id: int
    speaker_id: int
    private: bool
    agreeing: bool
    unasked: bool = False
    cause: Cause | None = None


async def record(call: ToolCall, spec: ToolSpec | None, st: Standing, turn: tuple[int, int], tier: Tier,
                 verdict: Verdict | None, got: ToolResult, config: OutsideConfig) -> Receipt | None:
    """Record the change `call` made, which ran at `tier` (`runs` for any change of an untainted turn), with what started
    the turn (a person's own tainted turn is its own cause) and how `got` says it is taken back. The receipt to show
    from memory when a judged change could not be stored, else None."""
    named = config.summary_arguments.get(call.name, ())
    label = config.unlabelled if spec is None or spec.label is None else spec.label
    shown = outside_summary.done_summary(label, call.arguments, named) if st.private else label
    cause = st.cause if st.unasked else Cause("turn", turn[1])
    action = DoneAction(st.household_id, st.speaker_id, *turn, call.name, shown, tier,
                        None if verdict is None else verdict.reason, None if verdict is None else verdict.explanation,
                        datetime.now(UTC), label, cause, got.undo)
    try:
        await services.get(OutsideRecord).done(action)
    except OutsideRecordUnavailable:
        logs.warning(log, "outside.unrecorded", conversation=turn[0], turn=turn[1], tool=call.name)
        if tier != "judged":
            return None
        return Receipt(label, shown if st.private else None, None if verdict is None else verdict.explanation)
    logs.info(log, "outside.recorded", conversation=turn[0], turn=turn[1], tool=call.name, tier=tier,
              cause=None if cause is None else cause.kind, cause_id=None if cause is None else cause.id,
              undo=None if got.undo is None else got.undo.kind)
    return None
