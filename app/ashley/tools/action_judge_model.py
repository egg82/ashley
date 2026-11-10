"""The ActionJudge by a model (`ashley.tools.action_judge`): one `action_judge` call per judged call, through `Inference`,
over the person's own words and the call's `View` alone. Its instructions are `action_judge.md`; its answer is structured
(`Answer`), and a reason the judge may not give, or any failure to answer, is JudgeUnavailable. The decision never depends
on the explanation: a blank one is kept blank and shown as no "why" line.

The route (`routes.json`, task `action_judge`) decides the model and its timeout. Logs nothing itself: `Inference` logs
`inference.call` per call and `outside.judged` carries the verdict's enums."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import services
from ..inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ..inference.model import DEFAULT_VARIANT, Message, Prompt, SystemPrompt
from .action_judge import ActionJudge, JudgeUnavailable, ModelReason, Verdict, View

TASK = "action_judge"
INSTRUCTIONS = Path(__file__).with_name("action_judge.md").read_text(encoding="utf-8").strip()
EXPLANATION_CHARS = 300


class Answer(BaseModel):
    """The judge's structured answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["run", "ask"]
    reason: ModelReason
    explanation: str = Field(description="One plain sentence to the person about why, in terms of what they asked.")


def request(words: Sequence[str], view: View) -> Prompt:
    """The prompt the judge is sent for the call `view` shows, given the person's `words`, oldest first."""
    fields = "\n".join(f"{k}: {v}" for k, v in view.fields.items())
    call = f"tool: {view.tool}" + (f"\n{fields}" if fields else "")
    said = json.dumps(list(words), ensure_ascii=False)
    message = Message("person", f"What the person said, oldest first, as a JSON list:\n{said}\n\nThe call:\n{call}")
    return Prompt(system={DEFAULT_VARIANT: SystemPrompt(INSTRUCTIONS)}, messages=(message,))


class ModelActionJudge(ActionJudge):
    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        try:
            got = await services.get(Inference).generate(TASK, request(words, view), Answer)
        except (InferenceUnavailable, InferenceRefused) as e:
            raise JudgeUnavailable(type(e).__name__) from e
        return Verdict(got.decision, got.reason, got.explanation.strip()[:EXPLANATION_CHARS])
