"""The verdict on a `judged` call of a tainted turn (`decisions.md`, "A turn that has read outside words asks before it
does anything consequential the person did not ask for"), reached in this order: the verdict already saved for the call
(a turn a new runner resumes does not judge it twice); no words of the person's, which asks without a judge; the source's
vetting of the call (`Tools.vetted`: a recipient nobody knows asks without a judge, else the view the source built); the
`ActionJudge` over the person's words and that view. A judge that cannot answer, or answers with anything but a clean
verdict, is `ask` (`judge_unavailable`). The verdict is saved through `Judged` before it is used.

Logs `outside.judged` with the conversation, turn, tool, tier, decision, the reason enum and duration_ms, and
`outside.judge_failed` with the error's class: never the words, the arguments or the explanation."""

import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from .. import logs, services
from ..inference.model import Tier, ToolCall, ToolSpec
from . import action_judge
from .action_judge import ActionJudge, Reason, Verdict
from .outside_config import OutsideConfig
from .tools import Tools

log = logging.getLogger("ashley.tools")
Words = Callable[[], Awaitable[Sequence[str]]]


class Judged(Protocol):
    async def judged(self, call_id: str, verdict: Verdict) -> None:
        """Save the verdict on the call `call_id`; raises when the turn cannot be saved, so the call does not run."""
        ...

    def judgement(self, call_id: str) -> Verdict | None:
        """The verdict saved for the call, None when it has none."""
        ...


async def verdict_on(call: ToolCall, spec: ToolSpec | None, tier: Tier, source: Tools, words: Words | None,
                     saved: Judged, config: OutsideConfig, turn: tuple[int, int] | None) -> Verdict:
    """The verdict on `call`, saved before it is returned; the one saved already when there is one."""
    prior = saved.judgement(call.id)
    if prior is not None:
        return prior
    started = time.monotonic()
    verdict = await _reached(call, spec, source, words, config, turn)
    await saved.judged(call.id, verdict)
    logs.info(log, "outside.judged", conversation=None if turn is None else turn[0], turn=None if turn is None else turn[1],
              tool=call.name, tier=tier, decision=verdict.decision, reason=verdict.reason,
              duration_ms=int((time.monotonic() - started) * 1000))
    return verdict


async def _reached(call: ToolCall, spec: ToolSpec | None, source: Tools, words: Words | None, config: OutsideConfig,
                   turn: tuple[int, int] | None) -> Verdict:
    try:
        said = () if words is None else tuple(await words())
        if not said:
            return Verdict("ask", "no_words", config.no_words)
        vetting = await source.vetted(call, said)
        if vetting is not None and vetting.ask is not None:
            return Verdict("ask", vetting.ask, _said(vetting.ask, config))
        parameters: Mapping[str, object] = {} if spec is None else spec.parameters
        view = vetting.view if vetting is not None and vetting.view is not None else action_judge.view_of(call, parameters)
        return action_judge.checked(await services.get(ActionJudge).decide(said, view))
    except Exception as e:
        logs.warning(log, "outside.judge_failed", conversation=None if turn is None else turn[0],
                     turn=None if turn is None else turn[1], tool=call.name, error=type(e).__name__)
        return Verdict("ask", "judge_unavailable", action_judge.UNJUDGED)


def _said(reason: Reason, config: OutsideConfig) -> str:
    """What the person is told when code, not the judge, asks."""
    return config.unknown_recipient if reason == "recipient_unknown" else action_judge.UNJUDGED
